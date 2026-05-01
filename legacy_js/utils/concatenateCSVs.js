const fs = require('fs-extra');
const path = require('path');

// Function to concatenate CSV files with optional custom headers and output directory creation
async function concatenateCSVs(folderPath, filePattern, outputFilePath, customHeaders = {}) {
    try {
        // Ensure the output directory exists
        const outputDir = path.dirname(outputFilePath);
        await fs.ensureDir(outputDir);

        // Read all files in the directory
        const files = await fs.readdir(folderPath);

        // Create a regular expression to match the file pattern
        const pattern = new RegExp(filePattern.replace('*', '.*'));

        // Filter files based on the pattern
        const csvFiles = files.filter(file => pattern.test(file) && file.endsWith('.csv'));

        if (csvFiles.length === 0) {
            console.log('CONCATENATE STEP: No files match the pattern.');
            return;
        }

        let headers = null;
        const rows = [];

        for (const file of csvFiles) {
            const filePath = path.join(folderPath, file);
            const fileContent = await fs.readFile(filePath, 'utf-8');
            const lines = fileContent.split('\n').filter(line => line.trim());

            // Set headers from the first file and skip the header in subsequent files
            if (!headers) {
                headers = lines[0].split(',');
                
                // Apply custom headers
                for (const [index, newHeader] of Object.entries(customHeaders)) {
                    const i = parseInt(index);
                    if (i >= 0 && i < headers.length) {
                        headers[i] = newHeader;
                    }
                }
                
                headers = headers.join(',');
                lines.slice(1).forEach(row => rows.push(row));
            } else {
                lines.slice(1).forEach(row => rows.push(row));
            }
        }

        if (headers) {
            // Write the concatenated result to the output file
            const outputContent = [headers, ...rows].join('\n');
            await fs.writeFile(outputFilePath, outputContent, 'utf-8');
            console.log(`Concatenated CSV file has been saved to ${outputFilePath}`);
        } else {
            console.log('No headers found.');
        }
    } catch (error) {
        console.error('Error concatenating CSV files:', error);
    }
}

module.exports = concatenateCSVs;