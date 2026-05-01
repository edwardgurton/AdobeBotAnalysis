const fs = require('fs');
const path = require('path');
const jsonTransform = require('./utils/jsonTransform');

function processJSONFiles(folderPath, filePattern = /\.json$/, optionalFolder = '') {
    return new Promise((resolve, reject) => {
        console.log(`Starting JSON file processing...`);
        console.log(`Source folder: ${folderPath}`);
        
        const csvFolderPath = path.join(path.dirname(folderPath), 'CSV');
        const writtenToCSVFolderPath = path.join(folderPath, 'writtenToCSV');
        const emptyJSONFolderPath = path.join(folderPath, 'EmptyJSON');

        // Create CSV folder if it doesn't exist
        if (!fs.existsSync(csvFolderPath)) {
            fs.mkdirSync(csvFolderPath);
            console.log(`Created CSV folder: ${csvFolderPath}`);
        }

        // Create the optional subdirectory if provided
        let finalCSVFolderPath = csvFolderPath;
        if (optionalFolder) {
            finalCSVFolderPath = path.join(csvFolderPath, optionalFolder);
            console.log(`Using optional subfolder: ${optionalFolder}`);
            if (!fs.existsSync(finalCSVFolderPath)) {
                fs.mkdirSync(finalCSVFolderPath);
                console.log(`Created optional subfolder: ${finalCSVFolderPath}`);
            }
        }

        // Create writtenToCSV subdirectory if it doesn't exist
        if (!fs.existsSync(writtenToCSVFolderPath)) {
            fs.mkdirSync(writtenToCSVFolderPath);
            console.log(`Created writtenToCSV folder: ${writtenToCSVFolderPath}`);
        }

        // Create EmptyJSON subdirectory if it doesn't exist
        if (!fs.existsSync(emptyJSONFolderPath)) {
            fs.mkdirSync(emptyJSONFolderPath);
            console.log(`Created EmptyJSON folder: ${emptyJSONFolderPath}`);
        }

        // Read files in the specified folder
        fs.readdir(folderPath, (err, files) => {
            if (err) {
                console.error('Error reading folder:', err);
                reject(err);
                return;
            }

            // Log all files read from the folder
            console.log(`All files read from the folder: ${folderPath}`);
            console.log(`Total files found: ${files.length}`);

            // Filter files based on filePattern
            const jsonFiles = files.filter(file => filePattern.test(file));
            console.log(`JSON files matching pattern: ${jsonFiles.length}`);

            if (jsonFiles.length === 0) {
                console.log('No JSON files found matching the pattern. Processing complete.');
                resolve({
                    processed: 0,
                    success: 0,
                    empty: 0,
                    errors: 0
                });
                return;
            }

            console.log(`Processing ${jsonFiles.length} JSON files...`);

            let processedCount = 0;
            let successCount = 0;
            let emptyCount = 0;
            let errorCount = 0;
            let hasError = false;

            // Process each JSON file
            jsonFiles.forEach(jsonFile => {
                const jsonFilePath = path.join(folderPath, jsonFile);
                console.log("jsonFilePath: ", jsonFilePath);
                const csvFileName = `${path.parse(jsonFile).name}.csv`;
                const csvFilePath = path.join(finalCSVFolderPath, csvFileName);
                const writtenToCSVFilePath = path.join(writtenToCSVFolderPath, jsonFile);
                const emptyJSONFilePath = path.join(emptyJSONFolderPath, jsonFile);

                // Transform JSON file
                const result = jsonTransform(jsonFilePath);

                processedCount++;

                if (result.empty) {
                    console.log(`File ${jsonFile} has empty rows. Moving to EmptyJSON folder.`);
                    emptyCount++;
                    fs.rename(jsonFilePath, emptyJSONFilePath, err => {
                        if (err) {
                            console.error(`Error moving ${jsonFile} to EmptyJSON folder:`, err);
                            hasError = true;
                        } else {
                            console.log(`Moved ${jsonFile} to EmptyJSON folder`);
                        }
                        checkCompletion();
                    });
                } else if (result.error) {
                    console.error(`Error processing file ${jsonFile}: ${result.message}`);
                    errorCount++;
                    hasError = true;
                    checkCompletion();
                } else if (result.success) {
                    // Write transformed data to CSV file
                    fs.writeFile(csvFilePath, result.data, err => {
                        if (err) {
                            console.error(`Error writing ${csvFileName}:`, err);
                            errorCount++;
                            hasError = true;
                            checkCompletion();
                        } else {
                            console.log(`Successfully wrote ${csvFileName}`);
                            
                            // Move original JSON file to writtenToCSV directory
                            fs.rename(jsonFilePath, writtenToCSVFilePath, err => {
                                if (err) {
                                    console.error(`Error moving ${jsonFile} to writtenToCSV:`, err);
                                    hasError = true;
                                } else {
                                    console.log(`Moved ${jsonFile} to writtenToCSV`);
                                    successCount++;
                                }
                                checkCompletion();
                            });
                        }
                    });
                }
            });

            function checkCompletion() {
                if (processedCount === jsonFiles.length) {
                    console.log(`\n=== Processing Summary ===`);
                    console.log(`Total files processed: ${processedCount}`);
                    console.log(`Successfully converted: ${successCount}`);
                    console.log(`Empty files moved: ${emptyCount}`);
                    console.log(`Errors encountered: ${errorCount}`);
                    console.log(`Processing complete.`);
                    
                    const results = {
                        processed: processedCount,
                        success: successCount,
                        empty: emptyCount,
                        errors: errorCount
                    };
                    
                    if (hasError && errorCount > 0) {
                        reject(new Error(`Processing completed with ${errorCount} errors. See logs for details.`));
                    } else {
                        resolve(results);
                    }
                }
            }
        });
    });
}

module.exports = processJSONFiles;