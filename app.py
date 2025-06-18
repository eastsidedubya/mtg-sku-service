from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta
import logging
from functools import lru_cache

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for caching
sku_data = {}
last_updated = None
UPDATE_INTERVAL_HOURS = 24

def download_and_process_skus():
    """Download and process the TCGPlayer SKU data"""
    global sku_data, last_updated

    logger.info("Starting SKU data download and processing...")

    try:
        # Download the SKU JSON file
        sku_url = "https://mtgjson.com/api/v5/TcgplayerSkus.json"
        response = requests.get(sku_url, stream=True)
        response.raise_for_status()

        # Parse the JSON data
        data = response.json()

        # Process and filter the data
        processed_data = {}
        total_skus = 0
        english_skus = 0

        for uuid, sku_list in data.get('data', {}).items():
            # Filter for English language only
            english_sku_list = [
                sku for sku in sku_list
                if sku.get('language', '').lower() == 'english'
            ]

            if english_sku_list:
                processed_data[uuid] = english_sku_list
                english_skus += len(english_sku_list)

            total_skus += len(sku_list)

        sku_data = processed_data
        last_updated = datetime.now()

        logger.info(f"SKU processing complete. Total SKUs: {total_skus}, English SKUs: {english_skus}, UUIDs: {len(processed_data)}")
        return True

    except Exception as e:
        logger.error(f"Error downloading/processing SKUs: {str(e)}")
        return False

def needs_update():
    """Check if SKU data needs to be updated"""
    if last_updated is None or not sku_data:
        return True

    return datetime.now() - last_updated > timedelta(hours=UPDATE_INTERVAL_HOURS)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'last_updated': last_updated.isoformat() if last_updated else None,
        'total_uuids': len(sku_data),
        'needs_update': needs_update()
    })

@app.route('/update', methods=['POST'])
def force_update():
    """Force update of SKU data"""
    success = download_and_process_skus()
    return jsonify({
        'success': success,
        'last_updated': last_updated.isoformat() if last_updated else None,
        'total_uuids': len(sku_data)
    })

@app.route('/skus', methods=['POST'])
def get_skus():
    """Get SKUs for provided UUIDs"""

    # Check if data needs updating
    if needs_update():
        logger.info("SKU data needs updating...")
        download_and_process_skus()

    try:
        # Get UUIDs from request
        request_data = request.get_json()
        if not request_data or 'uuids' not in request_data:
            return jsonify({'error': 'Missing uuids in request body'}), 400

        uuids = request_data['uuids']
        if not isinstance(uuids, list):
            return jsonify({'error': 'uuids must be an array'}), 400

        # Get requested conditions (default to all if not specified)
        requested_conditions = request_data.get('conditions', [
            'Near Mint', 'Lightly Played', 'Moderately Played',
            'Heavily Played', 'Damaged'
        ])

        # Get requested printings (default to all if not specified)
        requested_printings = request_data.get('printings', ['Normal', 'Foil'])

        # Process each UUID
        results = {}
        for uuid in uuids:
            if uuid in sku_data:
                # Filter by condition and printing
                filtered_skus = []
                for sku in sku_data[uuid]:
                    condition = sku.get('condition', '')
                    printing = sku.get('printing', '')

                    if (condition in requested_conditions and
                        printing in requested_printings):
                        filtered_skus.append({
                            'skuId': sku.get('skuId'),
                            'productId': sku.get('productId'),
                            'condition': condition,
                            'printing': printing,
                            'language': sku.get('language')
                        })

                results[uuid] = filtered_skus
            else:
                results[uuid] = []

        return jsonify({
            'success': True,
            'results': results,
            'total_requested': len(uuids),
            'total_found': len([uuid for uuid, skus in results.items() if skus])
        })

    except Exception as e:
        logger.error(f"Error processing SKU request: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/sku/<uuid>', methods=['GET'])
def get_sku_by_uuid(uuid):
    """Get SKUs for a single UUID"""

    # Check if data needs updating
    if needs_update():
        logger.info("SKU data needs updating...")
        download_and_process_skus()

    try:
        # Get query parameters
        conditions = request.args.getlist('condition') or [
            'Near Mint', 'Lightly Played', 'Moderately Played',
            'Heavily Played', 'Damaged'
        ]
        printings = request.args.getlist('printing') or ['Normal', 'Foil']

        if uuid in sku_data:
            # Filter by condition and printing
            filtered_skus = []
            for sku in sku_data[uuid]:
                condition = sku.get('condition', '')
                printing = sku.get('printing', '')

                if condition in conditions and printing in printings:
                    filtered_skus.append({
                        'skuId': sku.get('skuId'),
                        'productId': sku.get('productId'),
                        'condition': condition,
                        'printing': printing,
                        'language': sku.get('language')
                    })

            return jsonify({
                'success': True,
                'uuid': uuid,
                'skus': filtered_skus
            })
        else:
            return jsonify({
                'success': False,
                'uuid': uuid,
                'error': 'UUID not found',
                'skus': []
            })

    except Exception as e:
        logger.error(f"Error processing single SKU request: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Initialize data on startup
    logger.info("Starting Flask application...")
    download_and_process_skus()

    # Run the app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
