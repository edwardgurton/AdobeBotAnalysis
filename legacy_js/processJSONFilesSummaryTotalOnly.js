const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');
const jsonTransformSummaryTotalOnly = require('./utils/jsonTransformSummaryTotalOnly');

async function processJSONFiles(folderPath, filePattern = /\.json$/, optionalFolder = '') {
    const csvFolderPath = path.join(path.dirname(folderPath), 'CSV');
    const writtenToCSVFolderPath = path.join(folderPath, 'writtenToCSV');

    // Create CSV folder if it doesn't exist
    if (!fsSync.existsSync(csvFolderPath)) {
        fsSync.mkdirSync(csvFolderPath);
    }

    // Create the optional subdirectory if provided
    let finalCSVFolderPath = csvFolderPath;
    if (optionalFolder) {
        finalCSVFolderPath = path.join(csvFolderPath, optionalFolder);
        if (!fsSync.existsSync(finalCSVFolderPath)) {
            fsSync.mkdirSync(finalCSVFolderPath);
        }
    }

    // Create writtenToCSV subdirectory if it doesn't exist
    if (!fsSync.existsSync(writtenToCSVFolderPath)) {
        fsSync.mkdirSync(writtenToCSVFolderPath);
    }

    try {
        // Read files in the specified folder
        const files = await fs.readdir(folderPath);
        
        // Log all files read from the folder
        console.log('All files read from the folder:', files);

        // Filter files based on filePattern
        const jsonFiles = files.filter(file => filePattern.test(file));
        console.log('JSON files matching the pattern:', jsonFiles);

        // Process each JSON file
        const processingPromises = jsonFiles.map(async (jsonFile) => {
            const jsonFilePath = path.join(folderPath, jsonFile);
            const csvFileName = `${path.parse(jsonFile).name}.csv`;
            const csvFilePath = path.join(finalCSVFolderPath, csvFileName);
            const writtenToCSVFilePath = path.join(writtenToCSVFolderPath, jsonFile);

            try {
                // Transform JSON file
                const transformedData = jsonTransformSummaryTotalOnly(jsonFilePath);

                // Check if transformedData is falsy
                if (!transformedData) {
                    console.log(`Skipping ${jsonFile} as transformation returned no data`);
                    return; // Continue to the next file
                }

                // Write transformed data to CSV file
                await fs.writeFile(csvFilePath, transformedData);
                console.log(`Successfully wrote ${csvFileName}`);
                
                // Move original JSON file to writtenToCSV directory
                await fs.rename(jsonFilePath, writtenToCSVFilePath);
                console.log(`Moved ${jsonFile} to writtenToCSV`);

            } catch (error) {
                console.error(`Error processing ${jsonFile}:`, error);
            }
        });

        // Wait for all files to be processed
        await Promise.all(processingPromises);
        console.log('All JSON files processed successfully');

    } catch (error) {
        console.error('Error reading folder:', error);
        throw error;
    }
}

module.exports = processJSONFiles;