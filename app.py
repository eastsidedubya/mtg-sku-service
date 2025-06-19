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

# Global variables for SKU caching
sku_data = {}
sku_last_updated = None
sku_is_updating = False
sku_update_lock = threading.Lock()

# Global variables for pricing caching
pricing_data = {}
pricing_last_updated = None
pricing_is_updating = False
pricing_update_lock = threading.Lock()

UPDATE_INTERVAL_HOURS = 24

# SKU Functions (your existing code)
def download_and_process_skus():
    """Download and process the TCGPlayer SKU data"""
    global sku_data, sku_last_updated, sku_is_updating
    
    with sku_update_lock:
        if sku_is_updating:
            return False
        sku_is_updating = True
    
    try:
        logger.info("Starting SKU data download and processing...")
        sku_url = "https://mtgjson.com/api/v5/TcgplayerSkus.json"
        response = requests.get(sku_url, stream=True, timeout=300)
        response.raise_for_status()
        
        data = response.json()
        processed_data = {}
        total_skus = 0
        english_skus = 0
        
        for uuid, sku_list in data.get('data', {}).items():
            english_sku_list = [
                sku for sku in sku_list
                if sku.get('language', '').lower() == 'english'
            ]
            if english_sku_list:
                processed_data[uuid] = english_sku_list
                english_skus += len(english_sku_list)
            total_skus += len(sku_list)
        
        sku_data = processed_data
        sku_last_updated = datetime.now()
        logger.info(f"SKU processing complete. Total SKUs: {total_skus}, English SKUs: {english_skus}, UUIDs: {len(processed_data)}")
        return True
        
    except Exception as e:
        logger.error(f"Error downloading/processing SKUs: {str(e)}")
        return False
    finally:
        sku_is_updating = False

# Pricing Functions
def download_and_process_prices():
    """Download and process the MTGJSON pricing data"""
    global pricing_data, pricing_last_updated, pricing_is_updating
    
    with pricing_update_lock:
        if pricing_is_updating:
            return False
        pricing_is_updating = True
    
    try:
        logger.info("Starting pricing data download and processing...")
        pricing_url = "https://mtgjson.com/api/v5/AllPricesToday.json"
        response = requests.get(pricing_url, stream=True, timeout=300)
        response.raise_for_status()
        
        data = response.json()
        processed_data = {}
        total_cards = 0
        tcg_paper_cards = 0
        
        for uuid, price_formats in data.get('data', {}).items():
            paper_prices = price_formats.get('paper', {})
            tcgplayer_prices = paper_prices.get('tcgplayer', {})
            
            if tcgplayer_prices:
                processed_data[uuid] = {'tcgplayer': tcgplayer_prices}
                tcg_paper_cards += 1
            total_cards += 1
        
        pricing_data = processed_data
        pricing_last_updated = datetime.now()
        logger.info(f"Pricing processing complete. Total cards: {total_cards}, TCGPlayer paper cards: {tcg_paper_cards}")
        return True
        
    except Exception as e:
        logger.error(f"Error downloading/processing prices: {str(e)}")
        return False
    finally:
        pricing_is_updating = False

# Helper functions
def sku_needs_update():
    if sku_last_updated is None or not sku_data:
        return True
    return datetime.now() - sku_last_updated > timedelta(hours=UPDATE_INTERVAL_HOURS)

def pricing_needs_update():
    if pricing_last_updated is None or not pricing_data:
        return True
    return datetime.now() - pricing_last_updated > timedelta(hours=UPDATE_INTERVAL_HOURS)

def ensure_sku_data_loaded():
    if sku_needs_update() and not sku_is_updating:
        thread = threading.Thread(target=download_and_process_skus)
        thread.daemon = True
        thread.start()
        return sku_is_updating
    return False

def ensure_pricing_data_loaded():
    if pricing_needs_update() and not pricing_is_updating:
        thread = threading.Thread(target=download_and_process_prices)
        thread.daemon = True
        thread.start()
        return pricing_is_updating
    return False

# Main Routes
@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        'service': 'MTG Data Service',
        'status': 'running',
        'services': {
            'sku_service': 'TCGPlayer SKU data',
            'pricing_service': 'TCGPlayer Paper Pricing data'
        },
        'endpoints': {
            'health': '/health',
            'sku_health': '/sku/health',
            'pricing_health': '/pricing/health',
            'sku_update': '/sku/update (POST)',
            'pricing_update': '/pricing/update (POST)',
            'skus': '/sku/bulk (POST)',
            'prices': '/pricing/bulk (POST)',
            'single_sku': '/sku/<uuid>',
            'single_price': '/pricing/<uuid>'
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Combined health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'sku_service': {
            'last_updated': sku_last_updated.isoformat() if sku_last_updated else None,
            'total_uuids': len(sku_data),
            'needs_update': sku_needs_update(),
            'is_updating': sku_is_updating
        },
        'pricing_service': {
            'last_updated': pricing_last_updated.isoformat() if pricing_last_updated else None,
            'total_uuids': len(pricing_data),
            'needs_update': pricing_needs_update(),
            'is_updating': pricing_is_updating
        }
    })

# SKU Routes (with /sku prefix)
@app.route('/sku/health', methods=['GET'])
def sku_health_check():
    return jsonify({
        'status': 'healthy',
        'last_updated': sku_last_updated.isoformat() if sku_last_updated else None,
        'total_uuids': len(sku_data),
        'needs_update': sku_needs_update(),
        'is_updating': sku_is_updating
    })

@app.route('/sku/update', methods=['POST'])
def force_sku_update():
    if sku_is_updating:
        return jsonify({'message': 'SKU update already in progress', 'is_updating': True}), 202
    
    thread = threading.Thread(target=download_and_process_skus)
    thread.daemon = True
    thread.start()
    return jsonify({'message': 'SKU update started', 'is_updating': True}), 202

@app.route('/sku/bulk', methods=['POST'])
def get_skus():
    """Get SKUs for provided UUIDs"""
    updating = ensure_sku_data_loaded()
    
    if not sku_data and not updating:
        return jsonify({
            'error': 'SKU data not available. Try calling /sku/update first.',
            'suggestion': 'POST to /sku/update endpoint to initialize data'
        }), 503
    
    if updating:
        return jsonify({
            'message': 'SKU data is being updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202
    
    try:
        request_data = request.get_json()
        if not request_data or 'uuids' not in request_data:
            return jsonify({'error': 'Missing uuids in request body'}), 400
        
        uuids = request_data['uuids']
        if not isinstance(uuids, list):
            return jsonify({'error': 'uuids must be an array'}), 400
        
        requested_conditions = request_data.get('conditions', [
            'Near Mint', 'Lightly Played', 'Moderately Played',
            'Heavily Played', 'Damaged'
        ])
        requested_printings = request_data.get('printings', ['Normal', 'Foil'])
        
        results = {}
        for uuid in uuids:
            if uuid in sku_data:
                filtered_skus = []
                for sku in sku_data[uuid]:
                    condition = sku.get('condition', '')
                    printing = sku.get('printing', '')
                    if (condition in requested_conditions and printing in requested_printings):
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
    update_was_just_triggered = ensure_sku_data_loaded()
    
    if not sku_data and (sku_is_updating or update_was_just_triggered):
        return jsonify({
            'message': 'SKU data is being loaded/updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202
    
    if not sku_data:
        return jsonify({
            'error': 'SKU data not available. Try POSTing to /sku/update.',
            'is_updating': sku_is_updating
        }), 503
    
    try:
        if uuid in sku_data:
            skus_for_uuid = sku_data[uuid]
            requested_conditions = request.args.getlist('condition')
            requested_printings = request.args.getlist('printing')
            
            requested_conditions = [c for c in requested_conditions if c and c.strip()]
            requested_printings = [p for p in requested_printings if p and p.strip()]
            
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
            
            return jsonify({
                'success': True,
                'uuid': uuid,
                'skus': final_filtered_skus,
                'total_skus_found': len(final_filtered_skus)
            })
        else:
            return jsonify({
                'success': False,
                'uuid': uuid,
                'error': 'UUID not found',
                'skus': []
            }), 404
            
    except Exception as e:
        logger.error(f"Error processing single SKU request for UUID {uuid}: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# Pricing Routes (with /pricing prefix)
@app.route('/pricing/health', methods=['GET'])
def pricing_health_check():
    return jsonify({
        'status': 'healthy',
        'last_updated': pricing_last_updated.isoformat() if pricing_last_updated else None,
        'total_uuids': len(pricing_data),
        'needs_update': pricing_needs_update(),
        'is_updating': pricing_is_updating
    })

@app.route('/pricing/update', methods=['POST'])
def force_pricing_update():
    if pricing_is_updating:
        return jsonify({'message': 'Pricing update already in progress', 'is_updating': True}), 202
    
    thread = threading.Thread(target=download_and_process_prices)
    thread.daemon = True
    thread.start()
    return jsonify({'message': 'Pricing update started', 'is_updating': True}), 202

@app.route('/pricing/bulk', methods=['POST'])
def get_prices():
    """Get TCGPlayer paper prices for provided UUIDs"""
    updating = ensure_pricing_data_loaded()
    
    if not pricing_data and not updating:
        return jsonify({
            'error': 'Pricing data not available. Try calling /pricing/update first.',
            'suggestion': 'POST to /pricing/update endpoint to initialize data'
        }), 503
    
    if updating:
        return jsonify({
            'message': 'Pricing data is being updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202
    
    try:
        request_data = request.get_json()
        if not request_data or 'uuids' not in request_data:
            return jsonify({'error': 'Missing uuids in request body'}), 400
        
        uuids = request_data['uuids']
        if not isinstance(uuids, list):
            return jsonify({'error': 'uuids must be an array'}), 400
        
        requested_price_types = request_data.get('price_types', ['normal', 'foil', 'etched'])
        
        results = {}
        for uuid in uuids:
            if uuid in pricing_data:
                tcgplayer_prices = pricing_data[uuid]['tcgplayer']
                filtered_prices = {}
                for price_type in requested_price_types:
                    if price_type in tcgplayer_prices:
                        filtered_prices[price_type] = tcgplayer_prices[price_type]
                
                results[uuid] = {'tcgplayer': filtered_prices} if filtered_prices else {}
            else:
                results[uuid] = {}
        
        return jsonify({
            'success': True,
            'results': results,
            'total_requested': len(uuids),
            'total_found': len([uuid for uuid, prices in results.items() if prices])
        })
        
    except Exception as e:
        logger.error(f"Error processing pricing request: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/pricing/<uuid>', methods=['GET'])
def get_price_by_uuid(uuid):
    """Get TCGPlayer paper prices for a single UUID"""
    update_was_just_triggered = ensure_pricing_data_loaded()
    
    if not pricing_data and (pricing_is_updating or update_was_just_triggered):
        return jsonify({
            'message': 'Pricing data is being loaded/updated. Please try again in a few minutes.',
            'is_updating': True
        }), 202
    
    if not pricing_data:
        return jsonify({
            'error': 'Pricing data not available. Try POSTing to /pricing/update.',
            'is_updating': pricing_is_updating
        }), 503
    
    try:
        if uuid in pricing_data:
            tcgplayer_prices = pricing_data[uuid]['tcgplayer']
            requested_price_types = request.args.getlist('price_type')
            requested_price_types = [pt for pt in requested_price_types if pt and pt.strip()]
            
            if not requested_price_types:
                filtered_prices = tcgplayer_prices
            else:
                filtered_prices = {}
                for price_type in requested_price_types:
                    if price_type.lower() in [pt.lower() for pt in tcgplayer_prices.keys()]:
                        actual_key = next(
                            (key for key in tcgplayer_prices.keys() 
                             if key.lower() == price_type.lower()), 
                            None
                        )
                        if actual_key:
                            filtered_prices[actual_key] = tcgplayer_prices[actual_key]
            
            return jsonify({
                'success': True,
                'uuid': uuid,
                'tcgplayer_prices': filtered_prices,
                'available_price_types': list(filtered_prices.keys())
            })
        else:
            return jsonify({
                'success': False,
                'uuid': uuid,
                'error': 'UUID not found or no TCGPlayer paper prices available',
                'tcgplayer_prices': {}
            }), 404
            
    except Exception as e:
        logger.error(f"Error processing single price request for UUID {uuid}: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/skus', methods=['POST'])
def get_skus_legacy():
    """Keep existing Apps Script calls working"""
    return get_skus()  # Calls the new sku/bulk function

@app.route('/update', methods=['POST']) 
def force_update_legacy():
    """Keep existing Apps Script calls working"""
    return force_sku_update()  # Calls the new sku/update function

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
