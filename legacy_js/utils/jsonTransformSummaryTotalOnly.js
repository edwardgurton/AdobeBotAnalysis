const { Parser } = require('@json2csv/plainjs');
const { flatten } = require('@json2csv/transforms');
const fs = require('fs');

function jsonTransformSummaryTotalOnly(filePath) {
    const baseFileName = filePath;
    const outputFileName = baseFileName.replace(/.*[\\\/]/, '');
    // console.log('baseFileName: ', baseFileName);
    // console.log('outputFileName: ', outputFileName);


    // Read the JSON file from filePath and parse it
    let JSONfile;
    try {
        const fileContent = fs.readFileSync(filePath, 'utf8');
        JSONfile = JSON.parse(fileContent);
    } catch (err) {
        console.error('Error reading or parsing JSON file:', err);
        //return '';
    }

    // Extract requestName from file name and import headers
    const clientName = outputFileName.split('_')[0];
    const requestName = outputFileName.split('_')[1];
    //console.log('requestName:', requestName, '/clientName:', clientName);    
    let headers;
    try {
        headers = require(`../config/headers/${requestName}/${clientName}`);
    } catch (e) {
        console.log('Error loading headers for specific request:', e);
        //return;
    }

    // Extract summary data instead of rows
    const summaryData = JSONfile.summaryData;
    const columnIds = JSONfile.columns.columnIds;
    const totals = summaryData.totals;

    const fileName = outputFileName.replace('.json', '');
    const fileNameCol = `${fileName}`;
    const parts = fileName.split('_');
    const fromDate = parts[parts.length - 2];
    const toDate = parts[parts.length - 1];
    //console.log("fileName:", fileName, "fromDate:", fromDate, "toDate:", toDate);

    // Create a single row with totals mapped to column IDs
    const summaryRow = {};
    
    // Map each total to its corresponding column ID
    columnIds.forEach((columnId, index) => {
        summaryRow[`column_${columnId}`] = totals[index] || 0;
    });

    // Add metadata columns
    summaryRow.fileName = fileNameCol;
    summaryRow.fromDate = fromDate;
    summaryRow.toDate = toDate;

    // Create array with single row for CSV processing
    const newArray = [summaryRow];

    const flattenOpts = {
        header: false,
        transforms: [
            flatten({ objects: false, arrays: true })
        ]
    };

    const parser = new Parser(flattenOpts);
    const csvNoHeaders = parser.parse(newArray);
    const csv = headers + csvNoHeaders;
    console.log("csv:\n", csv)
    return csv;
}

module.exports = jsonTransformSummaryTotalOnly;