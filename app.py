from flask import Flask, jsonify, request
import requests
import json
import threading
import time
from datetime import datetime, timedelta
import logging
import os

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MTGDataService:
    def __init__(self):
        self.sku_data = {}
        self.price_data = {}
        self.last_sku_update = None
        self.last_price_update = None
        self.sku_lock = threading.Lock()
        self.price_lock = threading.Lock()
        self.update_in_progress = {'sku': False, 'price': False}
        
        # URLs
        self.sku_url = "https://mtgjson.com/api/v5/AllPrintings.json"
        self.price_url = "https://mtgjson.com/api/v5/AllPricesToday.json"
        
        # Start background update threads
        self.start_background_updates()
    
    def start_background_updates(self):
        """Start background threads for data updates"""
        sku_thread = threading.Thread(target=self._periodic_sku_update, daemon=True)
        price_thread = threading.Thread(target=self._periodic_price_update, daemon=True)
        sku_thread.start()  
        price_thread.start()
        logger.info("Background update threads started")
    
    def _periodic_sku_update(self):
        """Periodically update SKU data every 24 hours"""
        self.update_sku_data()  # Initial load
        while True:
            time.sleep(24 * 60 * 60)  # 24 hours
            self.update_sku_data()
    
    def _periodic_price_update(self):
        """Periodically update price data every 24 hours"""
        time.sleep(300)  # Wait 5 minutes after SKU data starts loading
        self.update_price_data()  # Initial load
        while True:
            time.sleep(24 * 60 * 60)  # 24 hours
            self.update_price_data()
    
    def update_sku_data(self):
        """Update SKU data from MTG JSON"""
        if self.update_in_progress['sku']:
            logger.info("SKU update already in progress")
            return {"success": False, "message": "Update already in progress"}
        
        self.update_in_progress['sku'] = True
        logger.info("Starting SKU data update...")
        
        try:
            response = requests.get(self.sku_url, timeout=300)
            response.raise_for_status()
            
            data = response.json()
            new_sku_data = {}
            
            # Process sets and cards
            for set_code, set_data in data.get('data', {}).items():
                if 'cards' in set_data:
                    for card in set_data['cards']:
                        if 'identifiers' in card and 'mtgjsonV4Id' in card['identifiers']:
                            uuid = card['identifiers']['mtgjsonV4Id']
                            
                            # Build SKU list for this card
                            skus = []
                            if 'finishes' in card:
                                for finish in card['finishes']:
                                    sku = f"{set_code}_{card.get('number', '0')}_{finish}"
                                    skus.append(sku)
                            
                            new_sku_data[uuid] = {
                                'name': card.get('name', ''),
                                'set': set_code,
                                'number': card.get('number', ''),
                                'skus': skus,
                                'rarity': card.get('rarity', ''),
                                'finishes': card.get('finishes', [])
                            }
            
            # Update data atomically
            with self.sku_lock:
                self.sku_data = new_sku_data
                self.last_sku_update = datetime.now()
            
            logger.info(f"SKU data updated successfully. {len(new_sku_data)} cards loaded.")
            return {"success": True, "message": f"Updated {len(new_sku_data)} cards"}
        
        except Exception as e:
            logger.error(f"Error updating SKU data: {str(e)}")
            return {"success": False, "message": str(e)}
        
        finally:
            self.update_in_progress['sku'] = False
    
    def update_price_data(self):
        """Update price data from MTG JSON - TCGPlayer Paper only"""
        if self.update_in_progress['price']:
            logger.info("Price update already in progress")
            return {"success": False, "message": "Update already in progress"}
        
        self.update_in_progress['price'] = True
        logger.info("Starting price data update...")
        
        try:
            response = requests.get(self.price_url, timeout=300)
            response.raise_for_status()
            
            data = response.json()
            new_price_data = {}
            
            # Process price data - filter for TCGPlayer Paper only
            for uuid, card_prices in data.get('data', {}).items():
                if 'paper' in card_prices and 'tcgplayer' in card_prices['paper']:
                    tcg_data = card_prices['paper']['tcgplayer']
                    
                    # Extract base market price - use retail prices
                    price_info = {
                        'market_price': None,
                        'buylist_price': None,
                        'currency': 'USD',
                        'last_updated': datetime.now().strftime('%Y-%m-%d')
                    }
                    
                    # Look for retail market price
                    if 'retail' in tcg_data:
                        retail = tcg_data['retail']
                        if 'normal' in retail:
                            price_info['market_price'] = retail['normal']
                        elif 'foil' in retail:
                            price_info['market_price'] = retail['foil']
                    
                    # Look for buylist price
                    if 'buylist' in tcg_data:
                        buylist = tcg_data['buylist']
                        if 'normal' in buylist:
                            price_info['buylist_price'] = buylist['normal']
                        elif 'foil' in buylist:
                            price_info['buylist_price'] = buylist['foil']
                    
                    # Only store if we have at least market price
                    if price_info['market_price'] is not None:
                        new_price_data[uuid] = price_info
            
            # Update data atomically
            with self.price_lock:
                self.price_data = new_price_data
                self.last_price_update = datetime.now()
            
            logger.info(f"Price data updated successfully. {len(new_price_data)} prices loaded.")
            return {"success": True, "message": f"Updated {len(new_price_data)} prices"}
        
        except Exception as e:
            logger.error(f"Error updating price data: {str(e)}")
            return {"success": False, "message": str(e)}
        
        finally:
            self.update_in_progress['price'] = False
    
    def get_sku_data(self, uuid):
        """Get SKU data for a specific UUID"""
        with self.sku_lock:
            return self.sku_data.get(uuid)
    
    def get_price_data(self, uuid):
        """Get price data for a specific UUID"""
        with self.price_lock:
            return self.price_data.get(uuid)
    
    def get_combined_data(self, uuid):
        """Get combined SKU and price data for a UUID"""
        sku_info = self.get_sku_data(uuid)
        price_info = self.get_price_data(uuid)
        
        if not sku_info:
            return None
        
        result = {
            'uuid': uuid,
            'skus': sku_info.get('skus', []),
            'name': sku_info.get('name', ''),
            'set': sku_info.get('set', ''),
            'number': sku_info.get('number', ''),
            'rarity': sku_info.get('rarity', ''),
            'finishes': sku_info.get('finishes', [])
        }
        
        if price_info:
            result['price'] = price_info
        else:
            result['price'] = None
        
        return result
    
    def get_bulk_combined_data(self, uuids):
        """Get combined data for multiple UUIDs"""
        results = []
        for uuid in uuids:
            data = self.get_combined_data(uuid)
            if data:
                results.append(data)
        return results
    
    def get_status(self):
        """Get service status"""
        with self.sku_lock:
            sku_count = len(self.sku_data)
            sku_last_update = self.last_sku_update
        
        with self.price_lock:
            price_count = len(self.price_data)
            price_last_update = self.last_price_update
        
        return {
            'sku_data': {
                'loaded': sku_count > 0,
                'count': sku_count,
                'last_updated': sku_last_update.isoformat() if sku_last_update else None,
                'update_in_progress': self.update_in_progress['sku']
            },
            'price_data': {
                'loaded': price_count > 0,
                'count': price_count,
                'last_updated': price_last_update.isoformat() if price_last_update else None,
                'update_in_progress': self.update_in_progress['price']
            }
        }

# Initialize the service
mtg_service = MTGDataService()

@app.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with price data status"""
    status = mtg_service.get_status()
    
    # Determine overall health
    healthy = (status['sku_data']['loaded'] and 
               status['price_data']['loaded'])
    
    return jsonify({
        'status': 'healthy' if healthy else 'loading',
        'service': 'MTG SKU & Price Service',
        'data_status': status
    }), 200 if healthy else 503

@app.route('/update', methods=['POST'])
def trigger_update():
    """Trigger manual update of both SKU and price data"""
    try:
        # Get update type from request
        data = request.get_json() or {}
        update_type = data.get('type', 'both')  # 'sku', 'price', or 'both'
        
        results = {}
        
        if update_type in ['sku', 'both']:
            results['sku'] = mtg_service.update_sku_data()
        
        if update_type in ['price', 'both']:
            results['price'] = mtg_service.update_price_data()
        
        return jsonify({
            'success': True,
            'message': 'Update triggered',
            'results': results
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/sku/<uuid>', methods=['GET'])
def get_sku_with_price(uuid):
    """Get SKU data with price information for a specific UUID"""
    try:
        data = mtg_service.get_combined_data(uuid)
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'UUID not found'
            }), 404
        
        return jsonify({
            'success': True,
            **data
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/skus', methods=['POST'])
def get_bulk_skus_with_prices():
    """Get SKU data with prices for multiple UUIDs"""
    try:
        data = request.get_json()
        if not data or 'uuids' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing uuids in request body'
            }), 400
        
        uuids = data['uuids']
        if not isinstance(uuids, list):
            return jsonify({
                'success': False,
                'message': 'uuids must be a list'
            }), 400
        
        results = mtg_service.get_bulk_combined_data(uuids)
        
        return jsonify({
            'success': True,
            'count': len(results),
            'results': results
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/status', methods=['GET'])
def get_status():
    """Get detailed service status"""
    return jsonify(mtg_service.get_status())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

