const { Parser } = require('@json2csv/plainjs');
const { flatten } = require('@json2csv/transforms');
const fs = require('fs');
const yaml = require('js-yaml');

function jsonTransform(filePath) {
    const baseFileName = filePath
    const outputFileName = baseFileName.replace(/.*[\\\/]/, '');
    //console.log('baseFileName: ', baseFileName);
    //console.log('outputFileName: ', outputFileName);

    // Read the JSON file from filePath and parse it
    let JSONfile;
    try {
        const fileContent = fs.readFileSync(filePath, 'utf8');
        JSONfile = JSON.parse(fileContent);
    } catch (err) {
        console.error(`Error reading or parsing JSON file ${filePath}:`, err);
        return { error: true, message: `Error reading or parsing JSON file: ${err.message}` };
    }

    // Check if rows is empty
    if (!JSONfile.rows || JSONfile.rows.length === 0) {
        return { empty: true };
    }

    // Extract requestName from file name and import headers
    const clientName = "Legend"
    const requestName = outputFileName.split('_')[1];
    let headers;
    try {
        headers = require(`../config/headers/${requestName}/${clientName}`);
    } catch (e) {
        console.error(`Error loading headers for specific request ${requestName}/${clientName}:`, e);
        return { error: true, message: `Error loading headers: ${e.message}` };
    }

    const rows = JSONfile.rows;
    if (rows.length === 0) {
        console.log(`No rows found in file: ${outputFileName}`);
        return headers || ''; // Return just headers if available, empty string if not
    }

    const fileName = outputFileName.replace('.json', '');
    const fileNameCol = `${fileName}`;
    const parts = fileName.split('_');
    const rsidName = parts[3];
    const botRuleName = parts[4];
    const fromDate = parts[parts.length - 2];
    const toDate = parts[parts.length - 1];


    // Modify newArray to ensure consistent order of itemId and value
    const newArray = rows.map(item => {
        const { itemId, value, data, ...rest } = item;
        return {
            itemId,
            value,
            ...data.reduce((acc, val, index) => ({ ...acc, [`data${index}`]: val }), {}),
            ...rest,
            fileName: fileNameCol,
            botRuleName: botRuleName,
            rsidName: rsidName,
            fromDate: fromDate,
            toDate: toDate
        };
    });

    const flattenOpts = {
        header: false,
        transforms: [
            flatten({ objects: false, arrays: true })
        ]
    };

    try {
        const parser = new Parser(flattenOpts);
        const csvNoHeaders = parser.parse(newArray);
        const csv = headers + csvNoHeaders;
        return { success: true, data: csv };
    } catch (err) {
        console.error(`Error parsing CSV for file ${filePath}:`, err);
        return { error: true, message: `Error parsing CSV: ${err.message}` };
    }
}

module.exports = jsonTransform;