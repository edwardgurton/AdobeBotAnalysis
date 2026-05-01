const fs = require('fs');
const path = require('path');
const getExpandedSegmentDetails = require('./getSegment');

async function saveSegmentToFile(segmentId, clientName) {
    try {
        // Get the segment details
        const segmentDetails = await getExpandedSegmentDetails(segmentId, clientName);

        if (!segmentDetails) {
            console.error('No segment details returned');
            return;
        }

        // Create the directory path
        const dirPath = path.join('usefulInfo', clientName, 'Segments');
        
        // Create directories if they don't exist
        fs.mkdirSync(dirPath, { recursive: true });

        // Create the file path with segmentId as filename
        const filePath = path.join(dirPath, `${segmentId}.json`);

        // Write the JSON file
        fs.writeFileSync(filePath, JSON.stringify(segmentDetails, null, 2));

        console.log(`Segment saved successfully to: ${filePath}`);
        return filePath;

    } catch (error) {
        console.error('Error saving segment:', error.message);
        throw error;
    }
}

module.exports = saveSegmentToFile;

// Usage example
// saveSegmentToFile('s3938_5f350ab3e9eaeb0c29b70489', 'Legend')
//     .then(filePath => console.log(`File saved at: ${filePath}`))
//     .catch(error => console.error('Error:', error));
