const fs = require('fs');
const path = require('path');

//path (the path of the file)
//val (the value to lookup)
//direction(left or right. If left, it will look for the val in the left of the key pair and return the right. If right, it will look in the right hand side and return the left).

function retrieveValue(filePath, val, direction) {
    try {
        // Read the file content
        const data = fs.readFileSync(path.resolve(filePath), 'utf8');
        
        // Split the content by new lines to process each key-value pair
        const lines = data.split('\n');

        for (let line of lines) {
            // Trim to avoid leading/trailing spaces or newlines
            line = line.trim();

            // Skip empty lines
            if (line === '') continue;

            // Split the line into key and value
            const [left, right] = line.split(':');

            if (direction === 'left' && left === val) {
                return right;
            } else if (direction === 'right' && right === val) {
                return left;
            }
        }

        // Return null if no match is found
        return null;
    } catch (err) {
        console.error("Error reading or processing the file:", err);
        return null;
    }
}

// Example usage:
// Assuming the file "pairs.txt" contains:
// key1:value1
// key2:value2
// key3:value3

module.exports = retrieveValue
