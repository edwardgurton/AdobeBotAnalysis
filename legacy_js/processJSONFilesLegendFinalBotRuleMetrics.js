const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');
const jsonTransformLegendFinalBotRuleMetrics = require('./utils/jsonTransformLegendFinalBotRuleMetrics');

async function processJSONFiles(folderPath, filePattern = /\.json$/, optionalFolder = '') {
    console.log("processJSONFiles folder path", folderPath);
    console.log("processJSONfiles file pattern", filePattern);

    const csvFolderPath = path.join(path.dirname(folderPath), 'CSV');
    const writtenToCSVFolderPath = path.join(folderPath, 'writtenToCSV');
    const emptyJSONFolderPath = path.join(folderPath, 'EmptyJSON');

    // Create necessary folders if they don't exist
    [csvFolderPath, writtenToCSVFolderPath, emptyJSONFolderPath].forEach(folder => {
        if (!fsSync.existsSync(folder)) {
            fsSync.mkdirSync(folder, { recursive: true });
        }
    });

    // Create the optional subdirectory if provided
    let finalCSVFolderPath = csvFolderPath;
    if (optionalFolder) {
        finalCSVFolderPath = path.join(csvFolderPath, optionalFolder);
        console.log("added optional folder path");
        if (!fsSync.existsSync(finalCSVFolderPath)) {
            fsSync.mkdirSync(finalCSVFolderPath, { recursive: true });
        }
    }

   // Create writtenToCSV subdirectory if it doesn't exist
   if (!fsSync.existsSync(writtenToCSVFolderPath)) {
    fsSync.mkdirSync(writtenToCSVFolderPath);
}

try {
    // Read files in the specified folder
    const files = await fs.readdir(folderPath);
    console.log('All files read from the folder:', files);

    // Filter files based on filePattern
    const jsonFiles = files.filter(file => filePattern.test(file));
    console.log('JSON files matching the pattern:', jsonFiles);

    if (jsonFiles.length === 0) {
        console.log('No JSON files found matching the pattern');
        return;
    }

    // Process each JSON file sequentially to avoid overwhelming the system
    for (const jsonFile of jsonFiles) {
        const jsonFilePath = path.join(folderPath, jsonFile);
        console.log("Processing jsonFilePath: ", jsonFilePath);
        
        const csvFileName = `${path.parse(jsonFile).name}.csv`;
        const csvFilePath = path.join(finalCSVFolderPath, csvFileName);
        const writtenToCSVFilePath = path.join(writtenToCSVFolderPath, jsonFile);
        const emptyJSONFilePath = path.join(emptyJSONFolderPath, jsonFile);

        try {
            // Transform JSON file
            const result = jsonTransformLegendFinalBotRuleMetrics(jsonFilePath);

            if (result.empty) {
                console.log(`File ${jsonFile} has empty rows. Moving to EmptyJSON folder.`);
                await fs.rename(jsonFilePath, emptyJSONFilePath);
                console.log(`Moved ${jsonFile} to EmptyJSON folder`);
            } else if (result.error) {
                console.error(`Error processing file ${jsonFile}: ${result.message}`);
            } else if (result.success) {
                // Write transformed data to CSV file
                await fs.writeFile(csvFilePath, result.data);
                console.log(`Successfully wrote ${csvFileName}`);
                
                // Move original JSON file to writtenToCSV directory
                await fs.rename(jsonFilePath, writtenToCSVFilePath);
                console.log(`Moved ${jsonFile} to writtenToCSV`);
            }
        } catch (fileError) {
            console.error(`Error processing individual file ${jsonFile}:`, fileError);
            // Continue with next file instead of stopping entire process
        }
    }

    console.log(`Completed processing ${jsonFiles.length} JSON files`);

} catch (error) {
    console.error('Error reading folder or processing files:', error);
    throw error;
}
}

module.exports = processJSONFiles;