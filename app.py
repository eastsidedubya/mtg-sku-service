from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta
import logging
from functools import lru_cache
import threading

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for caching
sku_data = {}
last_updated = None
UPDATE_INTERVAL_HOURS = 24
is_updating = False
update_lock = threading.Lock()


def download_and_process_skus():
    """Download and process the TCGPlayer SKU data"""
    global sku_data, last_updated, is_updating

    with update_lock:
        if is_updating:
            return False
        is_updating = True

    try:
        logger.info("Starting SKU data download and processing...")

        # Download the SKU JSON file
        sku_url = "https://mtgjson.com/api/v5/TcgplayerSkus.json"
        response = requests.get(sku_url, stream=True, timeout=300)
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

        logger.info(
            f"SKU processing complete. Total SKUs: {total_skus}, English SKUs: {english_skus}, UUIDs: {len(processed_data)}")
        return True

    except Exception as e:
        logger.error(f"Error downloading/processing SKUs: {str(e)}")
        return False
    finally:
        is_updating = False


def needs_update():
    """Check if SKU data needs to be updated"""
    if last_updated is None or not sku_data:
        return True

    return datetime.now() - last_updated > timedelta(hours=UPDATE_INTERVAL_HOURS)


def ensure_data_loaded():
    """Ensure SKU data is loaded, load it if necessary"""
    if needs_update() and not is_updating:
        # Start background update
        thread = threading.Thread(target=download_and_process_skus)
        thread.daemon = True
        thread.start()
        return is_updating
    return False


@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        'service': 'MTG SKU Service',
        'status': 'running',
        'endpoints': {
            'health': '/health',
            'update': '/update (POST)',
            'skus': '/skus (POST)',
            'single_sku': '/sku/<uuid>'
        }
    })


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'last_updated': last_updated.isoformat() if last_updated else None,
        'total_uuids': len(sku_data),
        'needs_update': needs_update(),
        'is_updating': is_updating
    })


@app.route('/update', methods=['POST'])
def force_update():
    """Force update of SKU data"""
    if is_updating:
        return jsonify({
            'message': 'Update already in progress',
            'is_updating': True
        }), 202

    # Start update in background thread
    thread = threading.Thread(target=download_and_process_skus)
    thread.daemon = True
    thread.start()

    return jsonify({
        'message': 'Update started',
        'is_updating': True
    }), 202


@app.route('/skus', methods=['POST'])
def get_skus():
    """Get SKUs for provided UUIDs"""

    # Check if we need to load data
    updating = ensure_data_loaded()

    # If no data and not updating, return error
    if not sku_data and not updating:
        return jsonify({
            'error': 'SKU data not available. Try calling /update first.',
            'suggestion': 'POST to /update endpoint to initialize data'
        }), 503

    # If data is updating, let user know
    if updating:
        return jsonify({
            'message': 'SKU data is being updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202

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
    """Get SKUs for a single UUID, filtered by query parameters."""

    update_was_just_triggered = ensure_data_loaded()

    if not sku_data and (is_updating or update_was_just_triggered):
        logger.info(
            f"Data for /sku/{uuid} not yet available, update in progress. is_updating: {is_updating}, triggered_now: {update_was_just_triggered}")
        return jsonify({
            'message': 'SKU data is being loaded/updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202

    if not sku_data:
        logger.error(f"Data request for /sku/{uuid} but no SKU data is loaded and no update is active.")
        return jsonify({
            'error': 'SKU data not available. An update might be in progress, has failed, or needs to be triggered. Try POSTing to /update or check service logs.',
            'is_updating': is_updating
        }), 503

    try:
        if uuid in sku_data:
            skus_for_uuid = sku_data[uuid]
            requested_conditions = request.args.getlist('condition')
            requested_printings = request.args.getlist('printing')
            
            # Filter out empty/null values
            requested_conditions = [c for c in requested_conditions if c and c.strip()]
            requested_printings = [p for p in requested_printings if p and p.strip()]
            
            logger.info(
                f"Request for UUID {uuid}. Requested conditions: {requested_conditions}, Requested printings: {requested_printings}")

            final_filtered_skus = []
            for sku in skus_for_uuid:
                sku_condition_lower = sku.get('condition', '').lower()
                sku_printing_lower = sku.get('printing', '').lower()

                requested_conditions_lower = [cond.lower() for cond in requested_conditions]
                requested_printings_lower = [prnt.lower() for prnt in requested_printings]

                condition_match = not requested_conditions_lower or sku_condition_lower in requested_conditions_lower
                printing_match = not requested_printings_lower or sku_printing_lower in requested_printings_lower

                if condition_match and printing_match:
                    final_filtered_skus.append({
                        'skuId': sku.get('skuId'),
                        'productId': sku.get('productId'),
                        'condition': sku.get('condition'),
                        'printing': sku.get('printing'),
                        'language': sku.get('language')
                    })

            if final_filtered_skus:
                logger.info(f"Found {len(final_filtered_skus)} SKUs for UUID {uuid} matching criteria.")
                return jsonify({
                    'success': True,
                    'uuid': uuid,
                    'skus': final_filtered_skus,
                    'total_skus_found': len(final_filtered_skus)
                })
            else:
                logger.info(
                    f"No SKUs found for UUID {uuid} matching criteria. Conditions: {requested_conditions}, Printings: {requested_printings}")
                return jsonify({
                    'success': True,
                    'uuid': uuid,
                    'skus': [],
                    'message': 'No SKUs found matching the specified condition and printing.',
                    'total_skus_found': 0
                })
        else:
            logger.info(f"UUID {uuid} not found in SKU data.")
            return jsonify({
                'success': False,
                'uuid': uuid,
                'error': 'UUID not found',
                'skus': []
            }), 404

    except Exception as e:
        logger.error(f"Error processing single SKU request for UUID {uuid}: {str(e)}")
        return jsonify({'error': 'Internal server error processing your request'}), 500
