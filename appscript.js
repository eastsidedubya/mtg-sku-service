// Global constant for the API endpoint
const MTGGRAPHQL_ENDPOINT = 'https://graphql.mtgjson.com/';

// Global object to track pending operations
const pendingOperations = {};

/**
 * @OnlyCurrentDoc
 * Adds a custom menu to the spreadsheet.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('MTGGraphQL')
    .addItem('Set API Token', 'setApiTokenDialog')
    .addSeparator()
    .addItem('Fetch Card Data by Name (New Sheet)', 'fetchCardDataByNameDialog')
    .addItem('Fetch Details for Current Row', 'fetchCardDetailsForRow')
    .addSeparator()
    .addItem('Fetch SKU for Current Row', 'fetchSkuForRow')
    .addItem('Batch Fetch All SKUs', 'batchFetchSkus')
    .addSeparator()
    .addItem('Force SKU Service Update', 'forceSkuServiceUpdate')
    .addSeparator()
    .addItem('Setup Trigger', 'setupEditTrigger')
    .addItem('Remove Trigger', 'removeEditTrigger')
    .addSeparator()
    .addItem('Test Row', 'testSingleRow')
    .addItem('Test Selection', 'processSelectedRows')
    .addItem('Process All', 'processAllRows')
    .addItem('Process All (Resume)', 'processAllRowsWithResume')
    .addItem('authorization', 'authorizeExternalRequests')
    .addToUi();
}

/** 
 * Sets up an installable edit trigger to handle auto-fetch
 */
/**
 * Sets up an installable edit trigger to handle auto-fetch
 */
function setupEditTrigger() {
  const ui = SpreadsheetApp.getUi();
  
  // Check if trigger already exists
  const existingTriggers = ScriptApp.getProjectTriggers();
  const mtgTriggerExists = existingTriggers.some(trigger => 
    trigger.getHandlerFunction() === 'onEditInstallable'
  );
  
  if (mtgTriggerExists) {
    const response = ui.alert(
      'Trigger Already Exists', 
      'MTGGraphQL auto-fetch trigger already exists. Do you want to recreate it?', 
      ui.ButtonSet.YES_NO
    );
    
    if (response === ui.Button.YES) {
      // Only remove our specific trigger
      existingTriggers.forEach(trigger => {
        if (trigger.getHandlerFunction() === 'onEditInstallable') {
          ScriptApp.deleteTrigger(trigger);
        }
      });
    } else {
      return; // User chose not to recreate
    }
  }
  
  try {
    // Create an installable edit trigger - using the spreadsheet reference
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    ScriptApp.newTrigger('onEditInstallable')
      .onEdit()
      .create();
    
    ui.alert('Success', 'MTGGraphQL auto-fetch trigger has been set up successfully!', ui.ButtonSet.OK);
  } catch (error) {
    console.error('Error setting up trigger:', error);
    
    // Try alternative method
    try {
      const ss = SpreadsheetApp.getActiveSpreadsheet();
      const trigger = ScriptApp.newTrigger('onEditInstallable')
        .onEdit()
        .create();
      
      ui.alert('Success', 'MTGGraphQL auto-fetch trigger has been set up successfully!', ui.ButtonSet.OK);
    } catch (secondError) {
      console.error('Second attempt failed:', secondError);
      ui.alert('Error', 'Failed to set up trigger. Please try:\n1. Refresh the page\n2. Check script permissions\n3. Try again\n\nError: ' + error.message, ui.ButtonSet.OK);
    }
  }
}

/** 
 * Removes only the MTGGraphQL installable edit trigger
 */
function removeEditTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  let removed = false;
  
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'onEditInstallable') {
      ScriptApp.deleteTrigger(trigger);
      removed = true;
    }
  });
  
  const message = removed ? 
    'MTGGraphQL auto-fetch trigger has been removed.' : 
    'No MTGGraphQL auto-fetch trigger found to remove.';
    
  SpreadsheetApp.getUi().alert('Success', message, SpreadsheetApp.getUi().ButtonSet.OK);
}

/** 
 * Generates a unique ID for the given row based on the formula logic
 */
function generateUniqueId(sheet, row) {
  // Get values from the row
  const h1Value = sheet.getRange('H1').getValue().toString();
  const setCode = sheet.getRange(row, 1).getValue().toString().trim().toUpperCase();
  const collectorNumber = sheet.getRange(row, 2).getValue().toString().trim();
  const printing = sheet.getRange(row, 4).getValue().toString().trim();
  
  if (!setCode) return ''; // Can't generate ID without set code
  
  // Format collector number as 4-digit padded string
  const paddedNumber = collectorNumber.padStart(4, '0');
  
  // Get first letter of printing, or "N" if empty
  const printingLetter = printing ? printing.charAt(0).toUpperCase() : 'N';
  
  // Build the base ID
  const baseId = h1Value + setCode + paddedNumber + printingLetter;
  
  // Count existing IDs with this base pattern (excluding current row)
  const allIds = sheet.getRange('G:G').getValues().flat();
  let counter = 0;
  
  for (let i = 0; i < allIds.length; i++) {
    // Skip the current row (i+1 because getValues is 0-indexed, rows are 1-indexed)
    if (i + 1 === row) continue;
    
    const id = allIds[i].toString();
    if (id.startsWith(baseId)) {
      counter++;
    }
  }
  
  // Format counter as 2-digit padded string
  const paddedCounter = counter.toString().padStart(2, '0');
  
  return baseId + paddedCounter;
}

/**  
 * Installable edit trigger - with 3-second debounce to prevent formula erasure
 * Now also handles condition changes in column E
 */
function onEditInstallable(e) {
  const sheet = e.source.getActiveSheet();
  const range = e.range;
  const row = range.getRow();
  const col = range.getColumn();
    
  // Only process if we're on the "ACQ" sheet and row 6 or higher
  if (sheet.getName() !== 'ACQ' || row < 6) return;
  
  // Handle condition changes in column E (immediate, no delay needed)
  if (col === 5) { // Column E - Condition
    console.log(`Row ${row}: Condition change detected in column E`);
    handleConditionChange(row);
    return;
  }
  
  // Handle Set (A), Number (B), Name (C), or Printing (D) columns with delay
  if (col !== 1 && col !== 2 && col !== 3 && col !== 4) return;
    
  const sheetId = sheet.getSheetId();
  const operationKey = `${sheetId}_${row}`;
    
  // Cancel any existing pending operation for this row
  if (pendingOperations[operationKey]) {
    console.log(`Cancelling previous operation for row ${row}`);
  }
    
  // Set up new delayed operation
  pendingOperations[operationKey] = true;
    
  // Process after 3-second delay
  Utilities.sleep(3000);
    
  // Check if operation was cancelled (another edit happened)
  if (!pendingOperations[operationKey]) {
    console.log(`Operation cancelled for row ${row}`);
    return;
  }
    
  // Clear the pending operation
  delete pendingOperations[operationKey];
    
  // Get current values (they might have changed during the delay)
  const setCode = sheet.getRange(row, 1).getValue().toString().trim().toUpperCase();
  const collectorNumber = sheet.getRange(row, 2).getValue().toString().trim();
    
  // Generate unique ID if we have set code
  if (setCode) {
    const uniqueId = generateUniqueId(sheet, row);
    if (uniqueId) {
      sheet.getRange(row, 7).setValue(uniqueId); // Column G
      console.log(`Row ${row}: Generated unique ID: ${uniqueId}`);
    }
  } else {
    // Clear unique ID if no set code
    sheet.getRange(row, 7).setValue('');
  }
    
  // Fetch card data if we have both Set and Number
  if (setCode && collectorNumber) {
    console.log(`Processing delayed fetch for row ${row}: Set [${setCode}], Number [${collectorNumber}]`);
    fetchCardBySetAndNumber(row, setCode, collectorNumber);
  } else if (!setCode || !collectorNumber) {
    // Clear Name and UUID if missing required data
    const currentNameValue = sheet.getRange(row, 3).getFormula();
    const currentUuidValue = sheet.getRange(row, 6).getFormula();
        
    if (!currentNameValue || !currentNameValue.startsWith('=')) {
      console.log(`Clearing Name for row ${row} (no formula detected)`);
      sheet.getRange(row, 3).setValue('');
    }
        
    if (!currentUuidValue || !currentUuidValue.startsWith('=')) {
      console.log(`Clearing UUID for row ${row} (no formula detected)`);
      sheet.getRange(row, 6).setValue('');
    }
  }
}

function handleConditionChange(row) {
  const sheet = SpreadsheetApp.getActiveSheet();

  // Get UUID from column F
  const uuid = sheet.getRange(row, 6).getValue().toString().trim();
  if (!uuid) {
    console.log(`Row ${row}: No UUID found, skipping SKU update`);
    return;
  }

  // Get the new condition from column E
  const newCondition = sheet.getRange(row, 5).getValue().toString().trim();

  // Get the printing from column D
  const printing = sheet.getRange(row, 4).getValue().toString().trim();

  console.log(`Row ${row}: Condition changed to "${newCondition}", updating SKU...`);

  processConditionChangeForRow(row, uuid, newCondition, printing);

  SpreadsheetApp.getActiveSpreadsheet().toast(`Row ${row}: SKU updated for condition "${newCondition}"`, "Condition Change", 2);
}

function processConditionChangeForRow(row, uuid, newCondition, printing) {
  console.log(`Row ${row}: Processing condition change - UUID: ${uuid}, Condition: ${newCondition}, Printing: ${printing}`);

  // Use the passed printing parameter here instead of printingInput
  const printingsToFetch = printing ? [printing] : ['Normal'];
  const conditionsToFetch = [newCondition];

  const skuData = fetchSkuByUuid(uuid, conditionsToFetch, printingsToFetch);

  // Rest of the function remains the same...
}


function setApiTokenDialog() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt(
    'Set API Token',
    'Please enter your MTGGraphQL Access Token:',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() == ui.Button.OK) {
    const token = response.getResponseText().trim();
    if (token) {
      PropertiesService.getUserProperties().setProperty('MTGGRAPHQL_ACCESS_TOKEN', token);
      ui.alert('Success', 'API Token saved successfully.', ui.ButtonSet.OK);
    } else {
      ui.alert('Error', 'API Token cannot be empty.', ui.ButtonSet.OK);
    }
  }
}
/**
 * Retrieves the stored API token.
 * @return {string|null} The API token or null if not set.
 */
function getApiToken() {
  const token = PropertiesService.getUserProperties().getProperty('MTGGRAPHQL_ACCESS_TOKEN');
  if (!token) {
    const ui = SpreadsheetApp.getUi();
    ui.alert(
      'API Token Not Set',
      'Please set your API token first using "MTGGraphQL > Set API Token".',
      ui.ButtonSet.OK
    );
    return null;
  }
  return token;
}
/**
 * Prompts user for a card name and fetches its data.
 */
function fetchCardDataByNameDialog() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt(
    'Fetch Card Data',
    'Enter the exact card name (e.g., Phelddagrif, Sol Ring):',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() == ui.Button.OK) {
    const cardName = response.getResponseText().trim();
    if (cardName) {
      fetchAndDisplayCardData(cardName);
    } else {
      ui.alert('Error', 'Card name cannot be empty.', ui.ButtonSet.OK);
    }
  }
}
/**
 * Fetches data for a specific card name and displays it in the active sheet.
 * @param {string} cardName The name of the card to search for.
 */
/**
 * Updated fetchAndDisplayCardData with correct query structure for name search
 */
function fetchAndDisplayCardData(cardName) {
  const token = getApiToken();
  if (!token) return;
  const ui = SpreadsheetApp.getUi();
  
  // We need to search through all sets to find cards with the given name
  // This is a more complex query since we can't directly filter by name
  const query = `
    query SearchCardByName {
      sets(
        page: { take: 100, skip: 0 }
        order: { order: ASC }
        input: {}
      ) {
        code
        name
        cards {
          uuid
          name
          faceName
          flavorName
          number
          setCode
          identifiers {
            tcgplayerProductId
          }
          prices {
            provider
            date
            cardType
            listType
            price
          }
        }
      }
    }
  `;
  
  const payload = { query: query };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: { 'Authorization': 'Bearer ' + token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  SpreadsheetApp.getActiveSpreadsheet().toast(`Searching for "${cardName}"...`, "MTGGraphQL");
  
  try {
    const response = UrlFetchApp.fetch(MTGGRAPHQL_ENDPOINT, options);
    const responseCode = response.getResponseCode();
    const responseBody = response.getContentText();
    
    if (responseCode === 200) {
      const jsonResponse = JSON.parse(responseBody);
      if (jsonResponse.errors) {
        console.error('GraphQL Errors:', JSON.stringify(jsonResponse.errors));
        ui.alert('GraphQL Error', 'The API returned an error: ' + JSON.stringify(jsonResponse.errors), ui.ButtonSet.OK);
        return;
      }
      
      // Collect all matching cards from all sets
      const matchingCards = [];
      if (jsonResponse.data && jsonResponse.data.sets) {
        jsonResponse.data.sets.forEach(set => {
          if (set.cards) {
            set.cards.forEach(card => {
              // Check if card name matches (exact match for now)
              if (card.name === cardName || 
                  card.faceName === cardName || 
                  card.flavorName === cardName) {
                matchingCards.push(card);
              }
            });
          }
        });
      }
      
      if (matchingCards.length > 0) {
        displayConsolidatedCardData(matchingCards);
        SpreadsheetApp.getActiveSpreadsheet().toast(`Found ${matchingCards.length} matches for "${cardName}"!`, "MTGGraphQL", 5);
      } else {
        ui.alert('No Data', `No cards found with the name "${cardName}".`, ui.ButtonSet.OK);
      }
    } else {
      console.error(`HTTP Error: ${responseCode} - ${responseBody}`);
      ui.alert(
        'API Request Failed',
        `Error fetching data. Status: ${responseCode}. Response: ${responseBody}`,
        ui.ButtonSet.OK
      );
    }
  } catch (e) {
    console.error('Script Error:', e);
    ui.alert('Script Error', 'An error occurred: ' + e.message, ui.ButtonSet.OK);
  }
}
/**
 * Displays consolidated card data in the "FetchCard" sheet.
 * The "Card Name" column will show flavorName or distinct faceName if available,
 * otherwise it shows the canonical card name.
 * @param {Array<Object>} cards The array of card objects from the API.
 */
function displayConsolidatedCardData(cards) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const targetSheetName = "FetchCard";
  let sheet = ss.getSheetByName(targetSheetName);
  
  if (sheet) {
    sheet.clearContents();
    sheet.clearFormats();
  } else {
    sheet = ss.insertSheet(targetSheetName);
  }
  
  ss.setActiveSheet(sheet);
  
  const headers = [
    'Set Code', 'Num', 'Card Name',
    'TCGPlayerID', 'Price', 'Foil Price'
  ];
  
  sheet.appendRow(headers);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold').setHorizontalAlignment('center');
  sheet.setFrozenRows(1);
  
  const rows = [];
  cards.forEach(card => {
    let tcgPlayerNormalPrice = '';
    let tcgPlayerFoilPrice = '';
    let tcgPlayerProductId = card.identifiers && card.identifiers.tcgplayerProductId ? card.identifiers.tcgplayerProductId : '';
    
    // Determine the name to display in the 'Card Name' column
    let displayName = card.name || ''; // Default to canonical name
    if (card.flavorName) {
      displayName = card.flavorName; // Override with flavorName if it exists
    } else if (card.faceName && card.faceName !== card.name) {
      // Override with faceName if it exists and is different from the canonical name
      displayName = card.faceName;
    }
    
    if (card.prices && card.prices.length > 0) {
      const tcgNormalPrices = card.prices
        .filter(p =>
          p.provider === 'tcgplayer' &&
          p.cardType === 'normal' &&
          p.listType === 'retail' &&
          p.price !== null && p.price !== undefined
        )
        .sort((a, b) => new Date(b.date) - new Date(a.date));
      
      if (tcgNormalPrices.length > 0) {
        tcgPlayerNormalPrice = tcgNormalPrices[0].price;
      }
      
      const tcgFoilPrices = card.prices
        .filter(p =>
          p.provider === 'tcgplayer' &&
          p.cardType === 'foil' &&
          p.listType === 'retail' &&
          p.price !== null && p.price !== undefined
        )
        .sort((a, b) => new Date(b.date) - new Date(a.date));
      
      if (tcgFoilPrices.length > 0) {
        tcgPlayerFoilPrice = tcgFoilPrices[0].price;
      }
    }
    
    rows.push([
      card.setCode || '',
      card.number || '',
      displayName,
      tcgPlayerProductId,
      tcgPlayerNormalPrice,
      tcgPlayerFoilPrice
    ]);
  });
  
  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
    for (let i = 1; i <= headers.length; i++) {
      sheet.autoResizeColumn(i);
    }
  } else {
    sheet.appendRow(["No price data found for the specified card matching criteria (TCGPlayer Normal/Foil Retail)."]);
  }
}
/**
 * Fetches details for the currently selected row
 */
function fetchCardDetailsForRow() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const activeRange = sheet.getActiveRange();
  const row = activeRange.getRow();
  
  if (row < 2) {
    SpreadsheetApp.getUi().alert('Error', 'Please select a data row (not the header).', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  // Get set code and collector number from current row
  const setCode = sheet.getRange(row, 1).getValue().toString().trim().toUpperCase();
  const collectorNumber = sheet.getRange(row, 2).getValue().toString().trim();
  
  if (!setCode || !collectorNumber) {
    SpreadsheetApp.getUi().alert('Error', 'Row must have Set Code (Column A) and Collector Number (Column B).', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  fetchCardBySetAndNumber(row, setCode, collectorNumber);
}
// SKU Service Configuration
const SKU_SERVICE_URL = 'https://mtg-sku-service-production.up.railway.app';

/**
 * Fetches SKU data for a specific UUID from your service
 * @param {string} uuid The card UUID
 * @param {Array} conditions Array of conditions to filter (optional)
 * @param {Array} printings Array of printings to filter (optional)
 * @return {Object} SKU data or null if error
 */
function fetchSkuByUuid(uuid, conditions = null, printings = null) {
  if (!uuid || uuid.trim() === '') {
    console.log('fetchSkuByUuid: Empty UUID provided');
    return null;
  }
  
  // Build query parameters
  let queryParams = [];
  if (conditions && conditions.length > 0) {
    conditions.forEach(condition => queryParams.push(`condition=${encodeURIComponent(condition)}`));
  }
  if (printings && printings.length > 0) {
    printings.forEach(printing => queryParams.push(`printing=${encodeURIComponent(printing)}`));
  }
  
  const queryString = queryParams.length > 0 ? '?' + queryParams.join('&') : '';
  const url = `${SKU_SERVICE_URL}/sku/${uuid}${queryString}`;
  
  const options = {
    method: 'GET',
    muteHttpExceptions: true
  };
  
  try {
    console.log(`Fetching SKU for UUID: ${uuid}`);
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    
    if (responseCode === 200) {
      const jsonResponse = JSON.parse(response.getContentText());
      if (jsonResponse.success) {
        console.log(`SKU fetch successful for ${uuid}: ${jsonResponse.skus.length} SKUs found`);
        return jsonResponse;
      } else {
        console.log(`No SKUs found for UUID: ${uuid}`);
        return null;
      }
    } else if (responseCode === 202) {
      // Service is updating
      console.log('SKU service is updating data, try again later');
      return { updating: true };
    } else {
      console.error(`SKU service error: ${responseCode} - ${response.getContentText()}`);
      return null;
    }
  } catch (error) {
    console.error(`Error fetching SKU for UUID ${uuid}: ${error.message}`);
    return null;
  }
}
/**
 * Formats the SKU API response to extract just the SKU ID.
 * @param {object} skuApiResponse The response object from the SKU service.
 * @return {number|string} The skuId if found, or an error message/empty string.
 */
function formatSkuData(skuApiResponse) {
  if (skuApiResponse.skus && skuApiResponse.skus.length > 0) {
    return skuApiResponse.skus[0].skuId; // Return just the skuId of the first SKU
  }
  
  console.error("formatSkuData called with unexpected data:", JSON.stringify(skuApiResponse));
  return 'Error processing SKU';
}
/**
 * Fetches SKU data for a specific row and populates the result
 * @param {number} row The row number to process
 */
function fetchSkuForRow(row) {
  const sheet = SpreadsheetApp.getActiveSheet();
  if (sheet.getName() !== 'ACQ') {
    console.log(`fetchSkuForRow: Not on ACQ sheet, currently on ${sheet.getName()}`);
    return;
  }

  const uuid = sheet.getRange(row, 6).getValue().toString().trim(); // Column F for UUID
  if (!uuid) {
    console.log(`Row ${row}: No UUID found in column F`);
    sheet.getRange(row, 13).setValue(''); // Clear Column M if no UUID
    return;
  }

  console.log(`Row ${row}: Fetching SKU for UUID: ${uuid}`);

  // Get the printing from column D, map to API format
  let printingInput = sheet.getRange(row, 4).getValue().toString().trim(); // Column D
  let printingsToFetch;
  if (printingInput) {
    const printingMap = {
      'normal': 'NON FOIL',
      'nonfoil': 'NON FOIL',
      'non foil': 'NON FOIL', 
      'non-foil': 'NON FOIL',
      'foil': 'FOIL'
    };
    const mappedPrinting = printingMap[printingInput.toLowerCase()] || printingInput.toUpperCase();
    printingsToFetch = [mappedPrinting];
  } else {
    printingsToFetch = ['NON FOIL']; // Default to NON FOIL
  }
  console.log(`Row ${row}: Using printings: ${printingsToFetch.join(', ')}`);
  
  // Get the condition from column E, map to API format  
  let conditionInput = sheet.getRange(row, 5).getValue().toString().trim(); // Column E
  const conditionsToFetch = conditionInput ? [conditionInput.toUpperCase()] : ['NEAR MINT'];
  console.log(`Row ${row}: Using conditions: ${conditionsToFetch.join(', ')}`);;
  
  // Call fetchSkuByUuid with specific conditions and printings
  const skuData = fetchSkuByUuid(uuid, conditionsToFetch, printingsToFetch);
  
  if (skuData && skuData.updating) {
    SpreadsheetApp.getActiveSpreadsheet().toast(
      `SKU service is updating data. Please try again in a few minutes.`,
      "SKU Service",
      5
    );
    return;
  }
  
  if (skuData && skuData.skus && skuData.skus.length > 0) {
    const formattedSku = formatSkuData(skuData);
    sheet.getRange(row, 13).setValue(formattedSku); // Column M for output
    console.log(`Row ${row}: SKU data updated in Column M: ${formattedSku}`);
    
    SpreadsheetApp.getActiveSpreadsheet().toast(
      `Row ${row}: Found ${skuData.skus.length} SKU(s) for specified criteria.`,
      "SKU Service",
      3
    );
  } else {
    sheet.getRange(row, 13).setValue('SKU not found for criteria'); // Column M for output
    console.log(`Row ${row}: No SKU data found for UUID ${uuid} with specified criteria.`);
    SpreadsheetApp.getActiveSpreadsheet().toast(
      `Row ${row}: No SKUs found for the specified printing/condition.`,
      "SKU Service",
      3
    );
  }
}
/**
 * Fetches SKU data for the currently selected row
 */
function fetchSkuForActiveRow() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const activeRange = sheet.getActiveRange();
  const row = activeRange.getRow();
  
  if (row < 2) {
    SpreadsheetApp.getUi().alert('Error', 'Please select a data row (not the header).', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  fetchSkuForRow(row);
}
/**
 * Fetches card data by set code and collector number using GraphQL
 * @param {number} row The row number to update
 * @param {string} setCode The set code
 * @param {string} collectorNumber The collector number
 */
function fetchCardBySetAndNumber(row, setCode, collectorNumber) {
  const token = getApiToken();
  if (!token) {
    console.log(`Row ${row}: No API token available`);
    return null;
  }

  const query = `
    query GetCardBySetAndNumber($code: String!) {
      sets(
        page: { take: 1, skip: 0 }
        order: { order: ASC }
        input: { code: $code }
      ) {
        id
        code
        name
        cards {
          uuid
          name
          faceName
          flavorName
          number
          setCode
        }
      }
    }
  `;

  const variables = { code: setCode };
  const payload = { query: query, variables: variables };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: { 'Authorization': 'Bearer ' + token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  SpreadsheetApp.getActiveSpreadsheet().toast(`Fetching ${setCode} #${collectorNumber}...`, "MTGGraphQL");

  try {
    const response = UrlFetchApp.fetch(MTGGRAPHQL_ENDPOINT, options);
    const data = JSON.parse(response.getContentText());
    
    if (data.errors) {
      console.error(`Row ${row}: GraphQL errors:`, data.errors);
      SpreadsheetApp.getUi().alert('GraphQL Error', 'API returned an error: ' + JSON.stringify(data.errors), SpreadsheetApp.getUi().ButtonSet.OK);
      return null;
    }
    
    if (data.data && data.data.sets && data.data.sets[0]) {
      const set = data.data.sets[0];
      const foundCard = set.cards.find(card => card.number === collectorNumber);
      
      if (foundCard) {
        const sheet = SpreadsheetApp.getActiveSheet();
        
        // Determine the name to display
        let displayName = foundCard.name || '';
        if (foundCard.flavorName) {
          displayName = foundCard.flavorName;
        } else if (foundCard.faceName && foundCard.faceName !== foundCard.name) {
          displayName = foundCard.faceName;
        }
        
        // Populate the sheet with the data
        sheet.getRange(row, 3).setValue(displayName); // Column C - Card Name
        sheet.getRange(row, 6).setValue(foundCard.uuid); // Column F - UUID
        
        console.log(`Row ${row}: Card data updated - Name: ${displayName}, UUID: ${foundCard.uuid}`);
        
        // Now automatically fetch SKU for this UUID
        fetchSkuForRowAuto(row, foundCard.uuid);
        
        SpreadsheetApp.getActiveSpreadsheet().toast(`Row ${row} updated with card data and SKU!`, "MTGGraphQL", 3);
        return foundCard;
      } else {
        console.log(`Row ${row}: Card #${collectorNumber} not found in set ${setCode} (${set.name})`);
        SpreadsheetApp.getUi().alert('Card Not Found', `Card #${collectorNumber} not found in set ${setCode}.`, SpreadsheetApp.getUi().ButtonSet.OK);
        return null;
      }
    } else {
      console.log(`Row ${row}: Set ${setCode} not found`);
      SpreadsheetApp.getUi().alert('Set Not Found', `Set ${setCode} not found.`, SpreadGraphApp.getUi().ButtonSet.OK);
      return null;
    }
  } catch (e) {
    console.error(`Row ${row}: API call failed: ${e.message}`);
    SpreadsheetApp.getUi().alert('API Error', 'Request failed: ' + e.message, SpreadsheetApp.getUi().ButtonSet.OK);
    return null;
  }
}

/**
 * Automatically fetches SKU data for a specific row and UUID
 * @param {number} row The row number to process
 * @param {string} uuid The card UUID
 */
function fetchSkuForRowAuto(row, uuid) {
  const sheet = SpreadsheetApp.getActiveSheet();
  if (sheet.getName() !== 'ACQ') {
    console.log(`fetchSkuForRowAuto: Not on ACQ sheet, currently on ${sheet.getName()}`);
    return;
  }
  if (!uuid || uuid.trim() === '') {
    console.log(`Row ${row}: No UUID provided for SKU fetch`);
    return;
  }
  console.log(`Row ${row}: Auto-fetching SKU for UUID: ${uuid}`);
  
  // Get the printing from column D, map to API format
  let printingInput = sheet.getRange(row, 4).getValue().toString().trim(); // Column D
  let printingsToFetch;
  if (printingInput) {
    const printingMap = {
      'normal': 'NON FOIL',
      'nonfoil': 'NON FOIL', 
      'non foil': 'NON FOIL',
      'non-foil': 'NON FOIL',
      'foil': 'FOIL'
    };
    const mappedPrinting = printingMap[printingInput.toLowerCase()] || printingInput.toUpperCase();
    printingsToFetch = [mappedPrinting];
  } else {
    printingsToFetch = ['NON FOIL']; // Default to NON FOIL
  }
  console.log(`Row ${row}: Using printings: ${printingsToFetch.join(', ')}`);
  
  // Get the condition from column E, map to API format
  let conditionInput = sheet.getRange(row, 5).getValue().toString().trim(); // Column E
  const conditionsToFetch = conditionInput ? [conditionInput.toUpperCase()] : ['NEAR MINT'];
  console.log(`Row ${row}: Using conditions: ${conditionsToFetch.join(', ')}`);

  // Call fetchSkuByUuid with specific conditions and printings
  const skuData = fetchSkuByUuid(uuid, conditionsToFetch, printingsToFetch);

  if (skuData && skuData.updating) {
    console.log(`Row ${row}: SKU service is updating, will retry later`);
    return;
  }

  if (skuData && skuData.skus && skuData.skus.length > 0) {
    const formattedSku = formatSkuData(skuData);
    sheet.getRange(row, 13).setValue(formattedSku); // Column M for output
    console.log(`Row ${row}: SKU data updated in Column M: ${formattedSku}`);
  } else {
    sheet.getRange(row, 13).setValue('SKU not found for criteria'); // Column M for output
    console.log(`Row ${row}: No SKU data found for UUID ${uuid} with specified criteria.`);
  }
}

/**
 * Processes all rows with resume capability
 */
function processAllRowsWithResume() {
  const sheet = SpreadsheetApp.getActiveSheet();
  if (sheet.getName() !== 'ACQ') {
    SpreadsheetApp.getUi().alert('Error', 'Please switch to the ACQ sheet first.', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert('Info', 'No data rows to process.', SpreadsheetApp.getUi().ButtonSet.OK);
    return;
  }
  
  // Get the last processed row from script properties
  const properties = PropertiesService.getScriptProperties();
  let startRow = parseInt(properties.getProperty('LAST_PROCESSED_ROW') || '2');
  
  // If we've already processed all rows, ask if user wants to restart
  if (startRow > lastRow) {
    const ui = SpreadsheetApp.getUi();
    const response = ui.alert(
      'Processing Complete',
      'All rows have been processed. Do you want to restart from the beginning?',
      ui.ButtonSet.YES_NO
    );
    if (response === ui.Button.YES) {
      startRow = 2;
      properties.setProperty('LAST_PROCESSED_ROW', '2');
    } else {
      return;
    }
  }
  
  SpreadsheetApp.getActiveSpreadsheet().toast(
    `Starting processing from row ${startRow} to ${lastRow}...`,
    "Batch Processing",
    5
  );
  
  const startTime = new Date().getTime();
  const maxExecutionTime = 4 * 60 * 1000; // 4 minutes in milliseconds
  
  for (let row = startRow; row <= lastRow; row++) {
    // Check execution time
    const currentTime = new Date().getTime();
    if (currentTime - startTime > maxExecutionTime) {
      properties.setProperty('LAST_PROCESSED_ROW', row.toString());
      SpreadsheetApp.getActiveSpreadsheet().toast(
        `Processing paused at row ${row}. Run again to continue.`,
        "Batch Processing",
        10
      );
      return;
    }
    
    // Get set code and collector number
    const setCode = sheet.getRange(row, 1).getValue().toString().trim().toUpperCase();
    const collectorNumber = sheet.getRange(row, 2).getValue().toString().trim();
    
    if (setCode && collectorNumber) {
      try {
        fetchCardBySetAndNumber(row, setCode, collectorNumber);
        
        // Small delay to avoid overwhelming the API
        Utilities.sleep(100);
        
        // Update progress
        if (row % 10 === 0) {
          SpreadsheetApp.getActiveSpreadsheet().toast(
            `Processed ${row - startRow + 1} rows...`,
            "Batch Processing"
          );
        }
      } catch (error) {
        console.error(`Error processing row ${row}: ${error.message}`);
        // Continue with next row
      }
    }
    
    // Update last processed row
    properties.setProperty('LAST_PROCESSED_ROW', (row + 1).toString());
  }
  
  // All rows processed
  properties.deleteProperty('LAST_PROCESSED_ROW');
  SpreadsheetApp.getActiveSpreadsheet().toast(
    `All rows processed successfully!`,
    "Batch Processing Complete",
    5
  );
}
/**
 * Resets the batch processing progress
 */
function resetBatchProgress() {
  const properties = PropertiesService.getScriptProperties();
  properties.deleteProperty('LAST_PROCESSED_ROW');
  
  const ui = SpreadsheetApp.getUi();
  ui.alert('Reset Complete', 'Batch processing progress has been reset. Next run will start from row 2.', ui.ButtonSet.OK);
}
/**
 * Shows current batch processing status
 */
function showBatchStatus() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const properties = PropertiesService.getScriptProperties();
  const lastProcessedRow = properties.getProperty('LAST_PROCESSED_ROW');
  const lastRow = sheet.getLastRow();
  
  const ui = SpreadsheetApp.getUi();
  
  if (!lastProcessedRow) {
    ui.alert('Batch Status', 'No batch processing in progress. Next run will start from row 2.', ui.ButtonSet.OK);
  } else {
    const nextRow = parseInt(lastProcessedRow);
    const remaining = Math.max(0, lastRow - nextRow + 1);
    ui.alert(
      'Batch Status', 
      `Next processing will start from row ${nextRow}.\nRemaining rows: ${remaining}`,
      ui.ButtonSet.OK
    );
  }
}

/**
 * Processes condition change for a specific row by re-fetching SKU with new condition
 * @param {number} row The row number
 * @param {string} uuid The card UUID
 * @param {string} newCondition The new condition value
 * @param {string} printing The printing value
 */
function processConditionChangeForRow(row, uuid, newCondition, printing) {
  const sheet = SpreadsheetApp.getActiveSheet();

  if (!uuid || uuid.trim() === '') {
    console.log(`Row ${row}: No UUID available for condition change processing`);
    return;
  }

  console.log(`Row ${row}: Processing condition change - UUID: ${uuid}, Condition: ${newCondition}, Printing: ${printing}`);

  // Use correct printing values that match your API
  let printingsToFetch;
  if (printing && printing.trim()) {
    // Map common printing values to API format
    const printingMap = {
      'normal': 'NON FOIL',
      'nonfoil': 'NON FOIL',
      'non foil': 'NON FOIL',
      'non-foil': 'NON FOIL',
      'foil': 'FOIL'
    };
    const mappedPrinting = printingMap[printing.toLowerCase()] || printing.toUpperCase();
    printingsToFetch = [mappedPrinting];
  } else {
    printingsToFetch = ['NON FOIL']; // Default to NON FOIL to match API
  }
  
  const conditionsToFetch = newCondition ? [newCondition.toUpperCase()] : ['NEAR MINT']; // Also uppercase conditions

  console.log(`Row ${row}: Fetching SKU with conditions: ${conditionsToFetch.join(', ')}, printings: ${printingsToFetch.join(', ')}`);

  // Call fetchSkuByUuid with the corrected values
  const skuData = fetchSkuByUuid(uuid, conditionsToFetch, printingsToFetch);

  // Rest of the function remains the same...
  if (skuData && skuData.updating) {
    console.log(`Row ${row}: SKU service is updating, condition change will be processed later`);
    SpreadsheetApp.getActiveSpreadsheet().toast(
      `Row ${row}: SKU service is updating. Please try again in a few minutes.`,
      "SKU Service",
      3
    );
    return;
  }

  if (skuData && skuData.skus && skuData.skus.length > 0) {
    const formattedSku = formatSkuData(skuData);
    sheet.getRange(row, 13).setValue(formattedSku); // Column M for SKU output
    console.log(`Row ${row}: SKU updated for condition change: ${formattedSku}`);
  } else {
    sheet.getRange(row, 13).setValue('SKU not found for criteria'); // Column M for output
    console.log(`Row ${row}: No SKU found for UUID ${uuid} with condition ${newCondition} and printing ${printing}`);
  }
}
