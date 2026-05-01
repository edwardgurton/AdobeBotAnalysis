const fs = require('fs');
const path = require('path');

/**
 * Reads bot rules from a specific CSV file in the bot rules directory
 * @param {string} fileName - Name of the CSV file (including .csv extension)
 * @param {string} outputType - Either "download" (default), "transform", "compare" or "segmentList"
 * @returns {Array|string} Array of bot rule objects (download), array of botRuleName strings (transform), 
 *                         or relative path to saved JSON file (segmentList)
 */
function readBotRulesFromCSV(fileName, outputType = 'download') {
    if (!fileName || !fileName.endsWith('.csv')) {
        throw new Error('fileName must be provided and include .csv extension');
    }

    if (!['download', 'transform', 'compare', 'segmentList'].includes(outputType)) {
        throw new Error('outputType must be either "download", "transform", or "segmentList"');
    }

    // Hardcoded directory path
    let lastPart;
    if (outputType == 'compare') {
      lastPart = 'BotCompareLists';
    } else {
      lastPart = 'BotRuleLists';
    }
    const csvDirectory = path.join(process.cwd(), 'usefulInfo', 'Legend', lastPart);
    const filePath = path.join(csvDirectory, fileName);

    try {
        // Read file synchronously
        const fileContent = fs.readFileSync(filePath, 'utf8');
        
        if (!fileContent.trim()) {
            console.warn(`File is empty: ${fileName}`);
            return outputType === 'segmentList' ? null : [];
        }

        // Simple CSV parsing - split by lines and commas
        const lines = fileContent.trim().split('\n');
        
        if (lines.length === 0) {
            console.warn(`No data found in file: ${fileName}`);
            return outputType === 'segmentList' ? null : [];
        }

        // Extract header row and log it
        const headerRow = lines[0].split(',').map(col => col.trim().replace(/"/g, ''));
        console.log(`Header row in ${fileName}:`, headerRow);

        // Find column indices
        const dimSegmentIdIndex = headerRow.findIndex(col => 
            col.toLowerCase().includes('dimsegmentid') || col.toLowerCase().includes('segment')
        );
        const botRuleNameIndex = headerRow.findIndex(col => 
            col.toLowerCase().includes('botrulename') || col.toLowerCase().includes('rule')
        );

        if (dimSegmentIdIndex === -1 || botRuleNameIndex === -1) {
            throw new Error(`Required columns not found. Expected 'dimSegmentId' and 'botRuleName', got: ${headerRow.join(', ')}`);
        }

        // Process data rows (skip header)
        const botRules = [];
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue; // Skip empty lines

            const columns = line.split(',').map(col => col.trim().replace(/"/g, ''));
            
            if (columns.length > Math.max(dimSegmentIdIndex, botRuleNameIndex)) {
                const dimSegmentId = columns[dimSegmentIdIndex];
                const botRuleName = columns[botRuleNameIndex];

                if (dimSegmentId && botRuleName) {
                    if (outputType === 'download') {
                        botRules.push({
                            dimSegmentId,
                            botRuleName
                        });
                    } else if (outputType === 'transform' || outputType === 'compare') {
                        botRules.push(botRuleName);
                    } else if (outputType === 'segmentList') {
                        // Transform botRuleName: strip equals and add prefix
                        const transformedName = `CompatabilityPrefix=${botRuleName.replace(/=/g, '')}`;
                        
                        botRules.push({
                            id: dimSegmentId,
                            name: transformedName
                        });
                    }
                } else {
                    console.warn(`Row ${i + 1} has empty fields, skipping`);
                }
            }
        }

        console.log(`Loaded ${botRules.length} bot rules from ${fileName}`);

        // Handle segmentList output type - save to JSON and return path
        if (outputType === 'segmentList') {
            // Create output directory if it doesn't exist
            const outputDir = path.join(process.cwd(), 'config', 'segmentLists', 'Legend');
            if (!fs.existsSync(outputDir)) {
                fs.mkdirSync(outputDir, { recursive: true });
            }

            // Generate output file name (replace .csv with .json)
            const baseFileName = path.basename(fileName, '.csv');
            const outputFileName = `${baseFileName}.json`;
            const outputPath = path.join(outputDir, outputFileName);

            // Write JSON file
            fs.writeFileSync(outputPath, JSON.stringify(botRules, null, 2), 'utf8');
            
            // Return relative path
            const relativePath = path.join('config', 'segmentLists', 'Legend', outputFileName);
            console.log(`Segment list saved to: ${relativePath}`);
            return relativePath;
        }

        return botRules;

    } catch (error) {
        if (error.code === 'ENOENT') {
            throw new Error(`File not found: ${fileName} in directory ${csvDirectory}`);
        }
        throw new Error(`Failed to read ${fileName}: ${error.message}`);
    }
}

module.exports = readBotRulesFromCSV;