from flask import Flask, jsonify, request
import requests
import json
import os
import logging
from datetime import datetime, timedelta

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
MTGJSON_PRICES_URL = 'https://mtgjson.com/api/v5/AllPricesToday.json'

# Cache files
PRICE_CACHE_FILE = 'price_cache.json'

# Cache durations (in seconds)
PRICE_CACHE_DURATION = 24 * 60 * 60  # 24 hours

def get_cached_price_data():
    """Get cached price data or fetch fresh if expired"""
    if os.path.exists(PRICE_CACHE_FILE):
        with open(PRICE_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        # Check if cache is still valid
        cache_time = datetime.fromisoformat(cache_data.get('cached_at', '1970-01-01'))
        if datetime.now() - cache_time < timedelta(seconds=PRICE_CACHE_DURATION):
            logger.info("Using cached price data")
            return cache_data.get('data')
    
    # Fetch fresh data
    logger.info("Fetching fresh price data from MTGJson")
    return fetch_fresh_price_data()

def fetch_fresh_price_data():
    """Fetch fresh price data from MTGJson and cache it"""
    try:
        response = requests.get(MTGJSON_PRICES_URL, timeout=30)
        response.raise_for_status()
        
        price_data = response.json()
        
        # Cache the data
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': price_data.get('data', {})
        }
        
        with open(PRICE_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        
        logger.info("Price data cached successfully")
        return price_data.get('data', {})
        
    except Exception as e:
        logger.error(f"Error fetching price data: {e}")
        return None

def normalize_condition(condition):
    """Normalize condition string for matching MTGJson conditions"""
    if not condition:
        return 'NM'
    
    # Convert to standard MTGJson condition format
    normalized = condition.strip()
    
    # Map common variations to MTGJson format
    condition_map = {
        'Near Mint': 'NM',
        'near mint': 'NM',
        'NM': 'NM',
        'nm': 'NM',
        'Lightly Played': 'LP',
        'lightly played': 'LP',
        'LP': 'LP',
        'lp': 'LP',
        'Moderately Played': 'MP',
        'moderately played': 'MP',
        'MP': 'MP',
        'mp': 'MP',
        'Heavily Played': 'HP',
        'heavily played': 'HP',
        'HP': 'HP',
        'hp': 'HP',
        'Damaged': 'DMG',
        'damaged': 'DMG',
        'DMG': 'DMG',
        'dmg': 'DMG'
    }
    
    return condition_map.get(normalized, normalized)

def normalize_printing(printing):
    """Normalize printing string for matching MTGJson printing types"""
    if not printing:
        return 'normal'
    
    normalized = printing.lower().strip()
    
    # Map common variations to MTGJson format
    printing_map = {
        'normal': 'normal',
        'regular': 'normal',
        'non-foil': 'normal',
        'nonfoil': 'normal',
        'foil': 'foil',
        'etched': 'etched',
        'showcase': 'normal',  # Showcase is usually normal finish
        'borderless': 'normal'  # Borderless is usually normal finish
    }
    
    return printing_map.get(normalized, normalized)

@app.route('/')
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'MTG Price Service',
        'version': '2.1.0',
        'endpoints': [
            '/price/<uuid>',
            '/price/<uuid>/debug',
            '/refresh-price-cache',
            '/cache-status'
        ]
    })

@app.route('/price/<uuid>/debug')
def debug_price_structure(uuid):
    """Debug endpoint to see the actual price data structure for a UUID"""
    try:
        price_data = get_cached_price_data()
        if not price_data:
            return jsonify({
                'success': False,
                'error': 'Price data not available'
            }), 503
        
        if uuid not in price_data:
            return jsonify({
                'success': False,
                'error': f'No price data found for UUID: {uuid}'
            }), 404
        
        # Return the raw structure for this UUID
        return jsonify({
            'success': True,
            'uuid': uuid,
            'raw_data': price_data[uuid]
        })
        
    except Exception as e:
        logger.error(f"Error in debug_price_structure: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/price/<uuid>')
def get_price(uuid):
    """Get price data for a specific UUID"""
    try:
        # Get query parameters
        conditions = request.args.getlist('condition')
        printings = request.args.getlist('printing')
        provider = request.args.get('provider', 'tcgplayer')
        
        # Default values
        if not conditions:
            conditions = ['Near Mint']
        if not printings:
            printings = ['Normal']
        
        # Normalize conditions and printings
        normalized_conditions = [normalize_condition(c) for c in conditions]
        normalized_printings = [normalize_printing(p) for p in printings]
        
        logger.info(f"Fetching price for UUID: {uuid}")
        logger.info(f"Original conditions: {conditions} -> Normalized: {normalized_conditions}")
        logger.info(f"Original printings: {printings} -> Normalized: {normalized_printings}")
        
        # Get price data
        price_data = get_cached_price_data()
        if not price_data:
            return jsonify({
                'success': False,
                'error': 'Price data not available'
            }), 503
        
        # Check if UUID exists
        if uuid not in price_data:
            return jsonify({
                'success': False,
                'error': f'No price data found for UUID: {uuid}',
                'hint': 'Use /price/<uuid>/debug to see available UUIDs'
            }), 404
        
        card_prices = price_data[uuid]
        
        # MTGJson structure: paper -> provider -> retail -> finish -> condition -> price
        if ('paper' not in card_prices):
            return jsonify({
                'success': False,
                'error': f'No paper price data for UUID: {uuid}',
                'available_formats': list(card_prices.keys()) if isinstance(card_prices, dict) else []
            }), 404
        
        if (provider not in card_prices['paper']):
            return jsonify({
                'success': False,
                'error': f'No {provider} price data for UUID: {uuid}',
                'available_providers': list(card_prices['paper'].keys()) if isinstance(card_prices['paper'], dict) else []
            }), 404
        
        if ('retail' not in card_prices['paper'][provider]):
            return jsonify({
                'success': False,
                'error': f'No retail price data for {provider} for UUID: {uuid}',
                'available_types': list(card_prices['paper'][provider].keys()) if isinstance(card_prices['paper'][provider], dict) else []
            }), 404
        
        retail_prices = card_prices['paper'][provider]['retail']
        found_prices = []
        
        # Navigate: retail -> finish -> condition -> price
        for printing in normalized_printings:
            if printing in retail_prices:
                finish_data = retail_prices[printing]
                if isinstance(finish_data, dict):
                    for condition in normalized_conditions:
                        if condition in finish_data:
                            price_value = finish_data[condition]
                            if price_value is not None:
                                found_prices.append({
                                    'condition': condition,
                                    'printing': printing,
                                    'price': float(price_value),
                                    'provider': provider
                                })
        
        if found_prices:
            return jsonify({
                'success': True,
                'uuid': uuid,
                'prices': found_prices,
                'total_found': len(found_prices)
            })
        else:
            # Provide debugging information
            available_finishes = list(retail_prices.keys()) if isinstance(retail_prices, dict) else []
            available_conditions = {}
            
            for finish in available_finishes:
                if isinstance(retail_prices[finish], dict):
                    available_conditions[finish] = list(retail_prices[finish].keys())
            
            return jsonify({
                'success': False,
                'error': 'No matching prices found for specified criteria',
                'requested_conditions': normalized_conditions,
                'requested_printings': normalized_printings,
                'available_finishes': available_finishes,
                'available_conditions': available_conditions,
                'hint': f'Use /price/{uuid}/debug to see full structure'
            }), 404
            
    except Exception as e:
        logger.error(f"Error in get_price: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'details': str(e)
        }), 500

@app.route('/refresh-price-cache', methods=['POST'])
def refresh_price_cache():
    """Manually refresh the price cache"""
    try:
        price_data = fetch_fresh_price_data()
        if price_data:
            # Get some stats about the data
            total_cards = len(price_data)
            sample_uuid = list(price_data.keys())[0] if price_data else None
            
            return jsonify({
                'success': True,
                'message': 'Price cache refreshed successfully',
                'refreshed_at': datetime.now().isoformat(),
                'total_cards': total_cards,
                'sample_uuid': sample_uuid
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to refresh price cache'
            }), 500
    except Exception as e:
        logger.error(f"Error refreshing price cache: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'details': str(e)
        }), 500

@app.route('/cache-status')
def cache_status():
    """Get status of price cache"""
    price_status = {'exists': False, 'age_hours': None, 'total_cards': 0}
    
    # Check price cache
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cache_time = datetime.fromisoformat(cache_data.get('cached_at', '1970-01-01'))
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            total_cards = len(cache_data.get('data', {}))
            price_status = {
                'exists': True, 
                'age_hours': round(age_hours, 2),
                'total_cards': total_cards
            }
        except Exception as e:
            logger.error(f"Error reading cache: {e}")
    
    return jsonify({
        'price_cache': price_status,
        'cache_duration_hours': PRICE_CACHE_DURATION / 3600
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
