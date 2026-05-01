const iterateDateRequests = require('./iterateDateRequests');
const fs = require('fs').promises;

async function iterateSegmentRequests(segmentsFilePath, jobName, delay = 0, fromDate, toDate, requestName, clientName, interval = 'day', rsid = "default") {
  console.log(`\n=== Starting iterateSegmentRequests ===`);
  console.log(`Segments file: ${segmentsFilePath}`);
  console.log(`Job name: ${jobName}`);
  console.log(`Date range: ${fromDate} to ${toDate}`);
  console.log(`Request name: ${requestName}`);
  console.log(`Client: ${clientName}`);
  console.log(`RSID: ${rsid}`);
  console.log(`Interval: ${interval}`);
  console.log(`Delay: ${delay}ms`);

  try {
    // Read the segments file
    console.log(`\n--- Reading segments file ---`);
    const segmentsData = await fs.readFile(segmentsFilePath, 'utf8');
    const segments = JSON.parse(segmentsData);
    
    console.log(`Loaded ${segments.length} segments`);

    // Process segments in batches of 12
    const batchSize = 12;
    const totalBatches = Math.ceil(segments.length / batchSize);
    
    console.log(`\n--- Processing ${totalBatches} batches of up to ${batchSize} segments each ---`);

    for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
      const startIndex = batchIndex * batchSize;
      const endIndex = Math.min(startIndex + batchSize, segments.length);
      const currentBatch = segments.slice(startIndex, endIndex);
      
      console.log(`\nProcessing batch ${batchIndex + 1}/${totalBatches} (segments ${startIndex + 1}-${endIndex})`);
      
      // Create promises for all segments in this batch
      const batchPromises = currentBatch.map(async (segment, index) => {
        const segmentId = segment.id;
        
        // Extract the part after the equals sign from the segment name
        const segmentNameParts = segment.name.split('=');
        const segmentSuffix = segmentNameParts.length > 1 ? segmentNameParts[1] : 'unknown';
        
        // Create fileNameExtra from jobName and segment suffix
        const fileNameExtra = `${jobName}_${segmentSuffix}`;
        
        console.log(`  Starting segment ${startIndex + index + 1}: ${segment.name}`);
        console.log(`    Segment ID: ${segmentId}`);
        console.log(`    File name extra: ${fileNameExtra}`);
        
        try {
          await iterateDateRequests(delay, fromDate, toDate, requestName, clientName, interval, segmentId, rsid, fileNameExtra);
          console.log(`  ✓ Completed segment ${startIndex + index + 1}: ${segmentSuffix}`);
        } catch (error) {
          console.error(`  ✗ Error processing segment ${startIndex + index + 1} (${segmentSuffix}):`, error.message);
          throw error; // Re-throw to handle at batch level
        }
      });
      
      // Wait for all segments in this batch to complete
      try {
        await Promise.all(batchPromises);
        console.log(`✓ Completed batch ${batchIndex + 1}/${totalBatches}`);
      } catch (error) {
        console.error(`✗ Error in batch ${batchIndex + 1}:`, error.message);
        throw error; // Re-throw to handle at function level
      }
      
      // Optional delay between batches (if needed)
      if (batchIndex < totalBatches - 1 && delay > 0) {
        console.log(`Waiting ${delay}ms before next batch...`);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
    
    console.log(`\n=== All segments processed successfully ===`);
    console.log(`Processed ${segments.length} segments across ${totalBatches} batches`);
    
  } catch (error) {
    console.error(`\n✗ Error in iterateSegmentRequests:`, error);
    throw error;
  } finally {
    // Explicitly exit the process after all segments have been processed
    console.log(`\n--- Exiting process to close rate limit manager ---`);
    process.exit(0);
  }
}

module.exports = iterateSegmentRequests;