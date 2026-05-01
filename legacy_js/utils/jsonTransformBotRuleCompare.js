const { Parser } = require('@json2csv/plainjs');
const { flatten } = require('@json2csv/transforms');
const fs = require('fs');

function jsonTransformBotRuleCompare(filePath) {
    const baseFileName = filePath;
    const outputFileName = baseFileName.replace(/.*[\\\/]/, '');

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

    // Parse the filename to extract metadata
    // AllTraffic Example: Legend_botInvestigationMetricsByBrowserType_Apuestasdeportivascom-01-BotCompare-FebMay25-CasinoSpielede-User-Agent-Compare-V1-AllTraffic_2023-12-01_2025-12-05.json
    // Segment Example: Legend_botInvestigationMetricsByBrowserType_Apuestasdeportivascom-01-BotCompare-FebMay25-CasinoSpielede-User-Agent-Compare-V1-Segment_DIMSEGs3938_6932b7194126b825f3792a2d_2023-12-01_2025-12-05.json
    const fileName = outputFileName.replace('.json', '');
    const parts = fileName.split('_');
    
    const clientName = parts[0]; // "Legend"
    const reportType = parts[1]; // "botInvestigationMetricsByBrowserType"
    const dimension = reportType.replace('botInvestigationMetricsBy', ''); // "BrowserType"
    const rsiDBotCompare = parts[2]; // Contains RSID-BOTCOMPARE
    const roundString = parts[3]; // E.g. "FebMay25RoundFour"
    const complexPart = parts[4]; //RuleName-Compare-compareVersion-TrafficType

    
    // Parse the complex part to extract RSID, Rule Name, and other details
    // Pattern: {RSID}-BOTCOMPARE_{Round}_{RuleName}-Compare-{Version}-{TrafficType}
    let rsidName = '';
    let botRuleName = '';
    let compareVersion = '';
    let trafficType = '';
    let segmentId = '';
    let segmentHash = '';
    
    // Extract RSID from before hyphen
    rsidName = rsiDBotCompare.split('-')[0];
    const complexParts = complexPart.split('-');
    botRuleName = complexParts[0]; // E.g. "User-Agent"`);
    compareVersion = complexParts[2]; // E.g. "V1"
    trafficType = complexParts[3]; // E.g. "AllTraffic" or "Segment"
    
    // Determine if this is a Compare (AllTraffic) or Segment (DimSeg) report
    const isSegment = trafficType === 'Segment';
    const isCompare = trafficType === 'AllTraffic' || trafficType === 'Compare';
    
    // If it's a segment, extract the segment ID and hash
    if (isSegment && parts.length > 5) {
        // Check if part[3] starts with DIMSEG
        if (parts[5] && parts[5].startsWith('DIMSEG')) {
            segmentId = parts[5]; // "DIMSEGs3938"
            if (parts[6] && parts[6].length === 24) { // Hash is typically 24 characters
                segmentHash = parts[6]; // "6932b7194126b825f3792a2d"
            }
        }
    }
    
    // Extract date range
    let startDate = '';
    let endDate = '';
    
    if (isSegment && segmentId) {
        // For segment files: part[5] and part[6] are dates (after DIMSEG and hash)
        startDate = parts[7] || '';
        endDate = parts[8] || '';
    } else {
        // For AllTraffic files: part[3] and part[4] are dates
        startDate = parts[5] || '';
        endDate = parts[6] || '';
    }

    // Hard-coded headers
    const headers = "id,Feature,unique_visitors,visits,Raw_Clickouts,Engaged_Visits,First_Time_Visits,Total_Seconds_Spent,Page_Views,fileName,clientName,reportType,dimension,rsidName,botRuleName,compareVersion,trafficType,isCompare,isSegment,segmentId,segmentHash,startDate,endDate\n";

    const rows = JSONfile.rows;
    if (rows.length === 0) {
        console.log(`No rows found in file: ${outputFileName}`);
        return headers || '';
    }

    // Transform the data
    const newArray = rows.map(item => {
        const { itemId, value, data, ...rest } = item;
        return {
            itemId,
            value,
            ...data.reduce((acc, val, index) => ({ ...acc, [`data${index}`]: val }), {}),
            ...rest,
            fileName: fileName,
            clientName: clientName,
            reportType: reportType,
            dimension: dimension,
            rsidName: rsidName,
            botRuleName: botRuleName,
            compareVersion: compareVersion,
            trafficType: trafficType,
            isCompare: isCompare,
            isSegment: isSegment,
            segmentId: segmentId,
            segmentHash: segmentHash,
            startDate: startDate,
            endDate: endDate
        };
    });

    const flattenOpts = {
        header: false,  // Don't auto-generate headers
        transforms: [
            flatten({ objects: false, arrays: true })
        ]
    };

    try {
        const parser = new Parser(flattenOpts);
        const csvNoHeaders = parser.parse(newArray);
        const csv = headers + csvNoHeaders;  // Prepend hard-coded headers
        return { success: true, data: csv };
    } catch (err) {
        console.error(`Error parsing CSV for file ${filePath}:`, err);
        return { error: true, message: `Error parsing CSV: ${err.message}` };
    }
}

module.exports = jsonTransformBotRuleCompare;