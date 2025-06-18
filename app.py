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
TCGPLAYER_API_URL = 'https://api.tcgplayer.com/catalog/products'
TCGPLAYER_TOKEN_URL = 'https://api.tcgplayer.com/token'
MTGJSON_PRICES_URL = 'https://mtgjson.com/api/v5/AllPricesToday.json'

# Cache files
SKU_CACHE_FILE = 'sku_cache.json'
PRICE_CACHE_FILE = 'price_cache.json'

# Cache durations (in seconds)
SKU_CACHE_DURATION = 24 * 60 * 60  # 24 hours
PRICE_CACHE_DURATION = 24 * 60 * 60  # 24 hours

# Environment variables
TCGPLAYER_PUBLIC_KEY = os.getenv('TCGPLAYER_PUBLIC_KEY')
TCGPLAYER_PRIVATE_KEY = os.getenv('TCGPLAYER_PRIVATE_KEY')

def get_tcgplayer_token():
    """Get TCGPlayer access token"""
    if not TCGPLAYER_PUBLIC_KEY or not TCGPLAYER_PRIVATE_KEY:
        logger.error("TCGPlayer API keys not configured")
        return None
    
    try:
        response = requests.post(TCGPLAYER_TOKEN_URL, data={
            'grant_type': 'client_credentials',
            'client_id': TCGPLAYER_PUBLIC_KEY,
            'client_secret': TCGPLAYER_PRIVATE_KEY
        })
        response.raise_for_status()
        return response.json().get('access_token')
    except Exception as e:
        logger.error(f"Error getting TCGPlayer token: {e}")
        return None

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
    """Normalize condition string for matching"""
    if not condition:
        return 'nearmint'
    
    # Convert to lowercase and remove spaces/special chars
    normalized = condition.lower().replace(' ', '').replace('-', '')
    
    # Map common variations
    condition_map = {
        'nm': 'nearmint',
        'nearmint': 'nearmint',
        'mint': 'nearmint',
        'lp': 'lightlyplayed',
        'lightlyplayed': 'lightlyplayed',
        'mp': 'moderatelyplayed',
        'moderatelyplayed': 'moderatelyplayed',
        'hp': 'heavilyplayed',
        'heavilyplayed': 'heavilyplayed',
        'damaged': 'damaged',
        'dmg': 'damaged'
    }
    
    return condition_map.get(normalized, normalized)

def normalize_printing(printing):
    """Normalize printing string for matching"""
    if not printing:
        return 'normal'
    
    normalized = printing.lower().replace(' ', '')
    
    # Map common variations
    printing_map = {
        'normal': 'normal',
        'regular': 'normal',
        'foil': 'foil',
        'etched': 'etched',
        'showcase': 'normal',
        'borderless': 'normal'
    }
    
    return printing_map.get(normalized, normalized)

@app.route('/')
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'MTG SKU and Price Service',
        'version': '2.0.0',
        'endpoints': [
            '/price/<uuid>',
            '/refresh-price-cache',
            '/cache-status'
        ]
    })

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
        
        logger.info(f"Fetching price for UUID: {uuid}, conditions: {normalized_conditions}, printings: {normalized_printings}")
        
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
                'error': f'No price data found for UUID: {uuid}'
            }), 404
        
        card_prices = price_data[uuid]
        
        # Navigate to paper -> provider -> retail
        if ('paper' not in card_prices or 
            provider not in card_prices['paper'] or 
            'retail' not in card_prices['paper'][provider]):
            return jsonify({
                'success': False,
                'error': f'No {provider} retail price data for UUID: {uuid}'
            }), 404
        
        retail_prices = card_prices['paper'][provider]['retail']
        found_prices = []
        
        # Find matching prices
        for condition in normalized_conditions:
            if condition in retail_prices:
                for printing in normalized_printings:
                    if printing in retail_prices[condition]:
                        price_value = retail_prices[condition][printing]
                        if price_value is not None:
                            found_prices.append({
                                'condition': condition,
                                'printing': printing,
                                'price': price_value,
                                'provider': provider
                            })
        
        if found_prices:
            return jsonify({
                'success': True,
                'uuid': uuid,
                'prices': found_prices
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No matching prices found for specified criteria',
                'available_conditions': list(retail_prices.keys()) if retail_prices else [],
                'requested_conditions': normalized_conditions,
                'requested_printings': normalized_printings
            }), 404
            
    except Exception as e:
        logger.error(f"Error in get_price: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/refresh-price-cache', methods=['POST'])
def refresh_price_cache():
    """Manually refresh the price cache"""
    try:
        price_data = fetch_fresh_price_data()
        if price_data:
            return jsonify({
                'success': True,
                'message': 'Price cache refreshed successfully',
                'refreshed_at': datetime.now().isoformat()
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
            'error': 'Internal server error'
        }), 500

@app.route('/cache-status')
def cache_status():
    """Get status of price cache"""
    price_status = {'exists': False, 'age_hours': None}
    
    # Check price cache
    if os.path.exists(PRICE_CACHE_FILE):
        try:
            with open(PRICE_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cache_time = datetime.fromisoformat(cache_data.get('cached_at', '1970-01-01'))
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            price_status = {'exists': True, 'age_hours': round(age_hours, 2)}
        except:
            pass
    
    return jsonify({
        'price_cache': price_status,
        'cache_duration_hours': PRICE_CACHE_DURATION / 3600
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
