// AD HOC - ONE BOT RULE ONLY
//BOT VALIDATION - ONLY ONE RULE DOWNLOAD 

const { downloadBotRuleValidationData, processBotRules } = require('../downloadBotRuleValidationData.js');

// Wrap in an async function
async function runDownload() {
    const fromDate = '2024-02-01';
    const toDate = '2026-02-01';
    const segmentId = "s3938_696f71469c86501a6ff760df";
    const botRuleName = "0194BOTRULOddspediaNLUserAgentANDMonitorResolution=2550x1640ANDPageURL=oddspediacomfootball";

    try {
        await downloadBotRuleValidationData(fromDate, toDate, 'Legend', segmentId, botRuleName);
        console.log('Download completed successfully!');
    } catch (error) {
        console.error('Download failed:', error);
    }
}

runDownload();

// VALIDATE THE DOWNLOAD - ONE OFF RULE
const { validateBotValidationDownload } = require('../validateBotValidationDownload.js');

validateBotValidationDownload(
    '2024-02-01', 
    '2026-02-01', 
    '0194BOTRULOddspediaNLUserAgentANDMonitorResolution=2550x1640ANDPageURL=oddspediacomfootball', 
    's3938_696f71469c86501a6ff760df'
);

// TRANSFORM AND CONCAT - ONE OFF RULE
const botValidationTransformConcat = require('../botValidationTransformConcat.js');
clientName = 'Legend';
processingStrings = ['0194BOTRULOddspediaNLUserAgentANDMonitorResolution=2550x1640ANDPageURL=oddspediacomfootball']
botValidationTransformConcat(clientName, processingStrings)