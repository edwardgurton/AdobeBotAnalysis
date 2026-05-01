const fs = require('fs');
const path = require('path');

/**
 * GenerateLegendReportSuiteLists - Creates formatted text files from Adobe report suite JSON data
 * @param {string} jsonFilePath - Path to the JSON file containing report suite data
 */
async function GenerateLegendReportSuiteLists(jsonFilePath) {
    try {
        console.log(`Processing JSON file: ${jsonFilePath}`);

        // Read and parse the JSON file
        const fileContent = fs.readFileSync(jsonFilePath, 'utf8');
        const reportSuitesData = JSON.parse(fileContent);

        if (!reportSuitesData.content || !Array.isArray(reportSuitesData.content)) {
            throw new Error('Invalid JSON structure: missing or invalid content array');
        }

        // Process each report suite and create formatted lines
        const formattedLines = reportSuitesData.content.map(suite => {
            let cleanName = suite.name
                .replace(/\s+/g, '') // Remove all spaces
                .replace(/\./g, '') // Remove all full stops
                .replace(/\s*-\s*Production/gi, ''); // Remove " - Production" (case insensitive)

            return `${suite.rsid}:${cleanName}`;
        });

        // Create the formatted content
        const formattedContent = formattedLines.join('\n');

        // Ensure the usefulInfo/Legend directory exists
        const legendDir = './usefulInfo/Legend';
        if (!fs.existsSync(legendDir)) {
            fs.mkdirSync(legendDir, { recursive: true });
        }

        // Ensure the ReportSuiteLists subdirectory exists
        const reportSuiteListsDir = path.join(legendDir, 'ReportSuiteLists');
        if (!fs.existsSync(reportSuiteListsDir)) {
            fs.mkdirSync(reportSuiteListsDir, { recursive: true });
        }

        // Save the main file
        const mainFilePath = path.join(legendDir, 'legendReportSuites.txt');
        fs.writeFileSync(mainFilePath, formattedContent, 'utf8');
        console.log(`Saved main report suite list to: ${mainFilePath}`);

        // Save the dated file
        const today = new Date();
        const dateString = today.getFullYear() +
            String(today.getMonth() + 1).padStart(2, '0') +
            String(today.getDate()).padStart(2, '0');
        
        const datedFilePath = path.join(reportSuiteListsDir, `legendReportSuites${dateString}.txt`);
        fs.writeFileSync(datedFilePath, formattedContent, 'utf8');
        console.log(`Saved dated report suite list to: ${datedFilePath}`);

        console.log(`Processed ${reportSuitesData.content.length} report suites`);

        return {
            mainFile: mainFilePath,
            datedFile: datedFilePath,
            count: reportSuitesData.content.length
        };

    } catch (error) {
        console.error('Error in GenerateLegendReportSuiteLists:', error);
        throw error;
    }
}

module.exports = GenerateLegendReportSuiteLists;