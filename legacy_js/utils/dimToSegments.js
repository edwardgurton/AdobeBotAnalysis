const fs = require('fs').promises;
const path = require('path');
const getAdobeTable = require('./getAdobeTable');
const extractValueId = require('./extractValueId');
const { createAdobeSegment } = require('./createSegment');

// Note: This function doesn't use metrics functionality, but remains compatible with addRequestDetails

async function dimToSegments(clientName, requestName, dimension, fromDate, toDate, segments = [], rsid = "default", numPairs = 10, debugMode = false) {
  console.log(`\n=== Starting dimToSegments function ===`);
  console.log(`Client: ${clientName}`);
  console.log(`Request Name: ${requestName}`);
  console.log(`Dimension: ${dimension}`);
  console.log(`Date range: ${fromDate} to ${toDate}`);
  console.log(`RSID: ${rsid}`);
  console.log(`Max pairs to process: ${numPairs}`);
  console.log(`Segments: ${segments.length > 0 ? segments.join(', ') : 'none'}`);
  console.log(`Debug mode: ${debugMode ? 'ON' : 'OFF'}`);
  
  // Clean the request name the same way addRequestDetails does
  const cleanedRequestName = requestName.replace(/[^a-zA-Z0-9]/g, '');
  const segmentId = segments.length > 0 ? segments[0] : undefined; // Use first segment for dimSegmentId
  const segmentArray = [];

  try {
    console.log(`\n--- Step 1: Fetching Adobe table ---`);
    console.log(`Cleaned request name: ${cleanedRequestName}`);
    
    if (debugMode) {
      console.log(`\n[DEBUG] getAdobeTable request parameters:`);
      console.log(`  fromDate: ${fromDate}`);
      console.log(`  toDate: ${toDate}`);
      console.log(`  cleanedRequestName: ${cleanedRequestName}`);
      console.log(`  clientName: ${clientName}`);
      console.log(`  segmentId: ${segmentId}`);
      console.log(`  rsid: ${rsid}`);
    }
    
    const reportTable = await getAdobeTable(fromDate, toDate, cleanedRequestName, clientName, segmentId, rsid)
    console.log(`Adobe table fetched successfully`);
    
    if (debugMode) {
      console.log(`\n[DEBUG] getAdobeTable full response:`);
      console.log(JSON.stringify(reportTable, null, 2));
    }
    
    console.log(`\n--- Step 2: Extracting value-ID pairs ---`);
    let pairs = await extractValueId(reportTable)

    // Check if pairs is a Promise and resolve it if necessary
    if (pairs instanceof Promise) {
      console.log(`Resolving pairs promise...`);
      pairs = await pairs
    }

    console.log(`Extracted ${pairs?.length || 0} pairs from report table`);
    
    if (debugMode) {
      console.log(`\n[DEBUG] Full pairs data:`);
      console.log(JSON.stringify(pairs, null, 2));
    } else {
      console.log("Pairs preview:", pairs?.slice(0, 3));
    }

    // Ensure pairs is an array before iterating
    if (!Array.isArray(pairs)) {
      throw new Error('Extracted pairs is not an array')
    }

    // Limit pairs to numPairs if specified
    const originalPairsCount = pairs.length;
    if (numPairs && pairs.length > numPairs) {
      pairs = pairs.slice(0, numPairs);
      console.log(`Limited pairs from ${originalPairsCount} to ${numPairs}`);
    }

    console.log(`\n--- Step 3: Creating segments ---`);
    console.log(`Processing ${pairs.length} pairs...`);

    // Create segments for each pair
    for (let i = 0; i < pairs.length; i++) {
      const pair = pairs[i];
      const { value, itemId } = pair;
      
      console.log(`\nProcessing pair ${i + 1}/${pairs.length}:`);
      console.log(`  Value: ${value}`);
      console.log(`  Item ID: ${itemId}`);
      
      if (debugMode) {
        console.log(`  [DEBUG] Full pair object:`, JSON.stringify(pair, null, 2));
      }
      
      try {
        const result = await createAdobeSegment(clientName, dimension, itemId, value);
        
        if (result) {
          console.log(`  ✓ Successfully created segment with ID: ${result.id}`);
          console.log(`  ✓ Original segment name: ${result.name}`);
          
          if (debugMode) {
            console.log(`  [DEBUG] Full createAdobeSegment response:`, JSON.stringify(result, null, 2));
          }
          
          // Update segment name format: replace colon with hyphen and remove spaces
          const formattedName = result.name.replace(/:/g, '-').replace(/\s+/g, '');
          console.log(`  ✓ Formatted segment name: ${formattedName}`);
          
          segmentArray.push({ id: result.id, name: formattedName });
        } else {
          console.log(`  ✗ Failed to create segment for ${value} - no result returned`);
        }
      } catch (segmentError) {
        console.error(`  ✗ Error creating segment for ${value}:`, segmentError.message);
        if (debugMode) {
          console.error(`  [DEBUG] Full error:`, segmentError);
        }
      }
    }

    console.log(`\n--- Step 4: Saving results ---`);
    console.log(`Created ${segmentArray.length} segments total`);

    // Save the segment array to a JSON file
    const fileName = `${clientName}_${rsid}_${cleanedRequestName}_segments_${new Date().toISOString().split('T')[0]}.json`;
    const dirPath = path.join('config', 'segmentLists', clientName);
    const filePath = path.join(dirPath, fileName);

    console.log(`Saving to: ${filePath}`);

    if (debugMode) {
      console.log(`\n[DEBUG] Final segment array to be saved:`);
      console.log(JSON.stringify(segmentArray, null, 2));
    }

    try {
      await fs.mkdir(dirPath, { recursive: true });
      await fs.writeFile(filePath, JSON.stringify(segmentArray, null, 2));
      console.log(`✓ Segment list saved successfully`);
      console.log(`✓ File contains ${segmentArray.length} segments`);
    } catch (error) {
      console.error("✗ Error saving segment list:", error);
      throw error;
    }

    console.log(`\n=== dimToSegments completed successfully ===`);
    
    // Return useful information for calling iterateSegmentRequests
    const result = {
      segmentArray: segmentArray,
      segmentCount: segmentArray.length,
      filePath: filePath,
      requestInfo: {
        clientName: clientName,
        requestName: cleanedRequestName,
        dimension: dimension,
        rsid: rsid
      },
      suggestedUsage: {
        iterateSegmentRequestsCall: `iterateSegmentRequests('${filePath}', 'YOUR_JOB_NAME', delay, fromDate, toDate, '${cleanedRequestName}', '${clientName}', interval, '${rsid}')`
      }
    };
    
    console.log(`✓ Segment file saved to: ${filePath}`);
    console.log(`✓ To process these segments with iterateSegmentRequests, use:`);
    console.log(`  ${result.suggestedUsage.iterateSegmentRequestsCall}`);
    
    return result;

  } catch (error) {
    console.error(`\n✗ Error in dimToSegments:`, error);
    if (debugMode) {
      console.error(`[DEBUG] Full error stack:`, error.stack);
    }
    throw error;
  }
}

module.exports = dimToSegments;