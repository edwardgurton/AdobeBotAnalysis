//iterateRsidsBotInvestigation.js is called directly. 
// Edits to update version number and toDate need to be done directly in code and saved

//with downloadAdobeTable, both dates are set to 00:00:00 in the request. So set the end date to the following day. E.g. to collect 2024-01-01, use 2024-01-01/2024-01-02.
//NB - iterate date requests takes care of this when used to make batch requests.
const getAdobeTable = require('./utils/getAdobeTable');
const downloadAdobeTable = require('./downloadAdobeTable');
const compileRequest = require('./utils/compileRequest');
const iterateRsidRequests = require('./utils/iterateRsidRequests');
const iterateDateRequests = require('./utils/iterateDateRequests')
const generateFromToDates = require ('./utils/generateFromToDates')
const getGlobalCompanyID = require('./utils/getGlobalCompanyID');
const getMultipleReportSuites = require('./utils/getMultipleReportSuites');
const retrieveValue = require('./utils/retrieveValue')
const addRequestDetails = require('./utils/addRequestDetails')
const deleteRequestDetails = require('./utils/deleteRequestDetails')
const buildSegmentsFromDimension = require('./buildSegmentsFromDimension')
const jsonTransformSummaryTotalOnly = require('./utils/jsonTransformSummaryTotalOnly')


//BLOCK TO DOWNLOAD A LEGEND TABLE

const downloadAdobeTable = require('./downloadAdobeTable');
const retrieveValue = require('./utils/retrieveValue')
const requestName = 'SegmentsBuilderCountry50'
const clientName = 'Legend'
const reportSuite = 'tribecasinoorg.test'
const legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt'
const fileName = retrieveValue(legendRsidLookup,reportSuite,'left')

downloadAdobeTable('2025-06-01','2025-06-02',requestName,clientName,undefined,reportSuite,fileName)
setTimeout(() => {
    process.exit(0);
}, 20000);
//adjust number if report may take longer to download.

//---------------------------------------------------------------------------------------------------

//BLOCK TO RUN LEGEND REPORT SUITE UPDATER

const LegendReportSuiteUpdater = require('./legendReportSuiteUpdater');

// Include virtual report suites (true/false), investigation threshold, validation threshold, optional fromDate in format YYYY-MM-DD, optional toDate in format YYYY-MM-DD
LegendReportSuiteUpdater(false, 1000, 1000, '2025-03-01','2025-05-31');

//---------------------------------------------------------------------------------------------------

//BLOCK TO RUN BOT INVESTIGATION COUNTRIES REPORT


const BotInvestigationGenerateCountrySegments = require('./BotInvestigationGenerateCountrySegments');

// Include virtual report suites (true/false), optional fromDate in format YYYY-MM-DD, optional toDate in format YYYY-MM-DD
BotInvestigationGenerateCountrySegments(1,"2025-06-01","2025-06-30")

//---------------------------------------------------------------------------------------------------

//BLOCK TO TRANSFORM FILES MATCHING GIVEN PATTERN - ASSUMING THEY'RE SAVED IN CLIENT/JSON

const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path'); 
const clientName2 = 'Legend' //update this
const fileName2 = 'TEMP1751629033' //update this
const fileNameRegexPattern = new RegExp(`.*${fileName2}.*\\.json$`);
const optionalFolder = undefined //update this to save to a folder other than clientname/csv
//const processJSONFiles = require('./processJSONFiles')
const processJSONFiles = require('./processJSONFilesSummaryTotalOnly')  
let readWriteSettings;
    try {
        readWriteSettings = yaml.load(fs.readFileSync('./config/read_write_settings/readWriteSettings.yaml', 'utf8'));
    } catch (error) {
        console.error('Error loading read/write settings:', error);
        process.exit = originalExit; // Restore original exit
        return;
    }

    const storageFolder = readWriteSettings.storage.folder;
    const folderPath = path.join(storageFolder, clientName2, 'JSON')
 
processJSONFiles(folderPath,fileNameRegexPattern,optionalFolder)

//---------------------------------------------------------------------------------------------------

//BLOCK TO PROCESS LEGEND BOT INVESTIGATION FILES


const botInvestigationTransformConcat = require('./botInvestigationTransformConcat')

//Version number should be string specified when calling iterateRsids. The downloadBatch is either 1 for the single country downloads, 2 for the country x rsid combinations.
botInvestigationTransformConcat("V4",2)

//---------------------------------------------------------------------------------------------------

const validateBotInvestigationTypeOne = require('./validateBotInvestigationTypeOne')

validateBotInvestigationTypeOne("4.2","2025-05-31")


//---------------------------------------------------------------------------------------------------

//BLOCK TO DOWNLOAD A ONE-OFF INVESTIGATION

const downloadBotInvestigationData = require('./downloadBotInvestigationData');

//select the reportsuite here
const suite = 'Coverscom'
const retrieveLegendRsid = require('./utils/retrieveLegendRsid');
const rsid = retrieveLegendRsid(suite)
console.log(rsid)

//to add a country segment, add these two lines
const countryName = 'Singapore'
const { getSegmentIdByDimValueName, getSegmentIdByDimValueNameIgnoreCase } = require('./utils/retrieveLegendCountrySegments');
const dimSegmentId = getSegmentIdByDimValueNameIgnoreCase(countryName)
console.log(dimSegmentId)

//Update the dates here.Lookback window should generally by 31 for a one-off investigation, but can be longer if needed.
const toDate = '2025-06-10';
const subtractDays = require('./utils/subtractDays');
const fromDate = subtractDays(toDate,46)

//run these two lines and note value for next step
const investigationPrefix = `botInvestigation-${suite}-${countryName}-${toDate}`;
console.log("investigationPrefix: ", investigationPrefix)

downloadBotInvestigationData(0,fromDate, toDate, 'Legend',dimSegmentId,rsid,investigationPrefix)

//---------------------------------------------------------------------------------------------------

//RUN TRANSFORM CONCAT FOR ONE-OFF

const botInvestigationTransformConcat = require('./botInvestigationTransformConcat')
botInvestigationTransformConcat("V0",3,{
    toDate: '2025-06-30',
    subtractDays: 46,
    botInvestigationPrefix: 'SportsBookReviewcom-Singapore-2025-06-30'
});

//---------------------------------------------------------------------------------------------------
//BOT VALIDATION - ONLY ONE RULE DOWNLOAD 

const { downloadBotRuleValidationData, processBotRules } = require('./downloadBotRuleValidationData.js');

// Wrap in an async function
async function runDownload() {
    const fromDate = '2023-08-01';
    const toDate = '2025-08-01';
    const segmentId = "s3938_68875fcb762ef06cc5283857";
    const botRuleName = "0099SBR-SG-UserAgent";

    try {
        await downloadBotRuleValidationData(fromDate, toDate, 'Legend', segmentId, botRuleName);
        console.log('Download completed successfully!');
    } catch (error) {
        console.error('Download failed:', error);
    }
}

runDownload();

//BOT VALIDATION - PROCESS MULTIPLE RULES
// Input rules as an array of objects with dimSegmentId and botRuleName properties. 

const { processBotRules } = require('./downloadBotRuleValidationData.js');

async function testProcessBotRules() {
    const fromDate = '2023-08-01';
    const toDate = '2025-08-01';

    const botRulesList = [
        {
            "dimSegmentId": "s3938_68875fcb762ef06cc5283857",
            "botRuleName": "0099SBR-SG-UserAgent"
        }
    ];
    
    try {
        await processBotRules(botRulesList, fromDate, toDate, 'Legend');
        console.log('Done!');
    } catch (error) {
        console.error('Error:', error);
    }
}

testProcessBotRules();

//BOT VALIDATION - VALIDATE ONE RULE

const { validateBotValidationDownload } = require('./validateBotValidationDownload.js');

validateBotValidationDownload(
    '2023-08-01', 
    '2025-08-01', 
    '0099SBR-SG-UserAgent', 
    's3938_68875fcb762ef06cc5283857'
);

//READ BOT RULES TEST
 const readBotRulesFromCSV = require('./utils/readBotRulesFromCSV.js');
 const testarray = readBotRulesFromCSV('exampleBotRuleList.csv','download')
 console.log(testarray);


//----------------------------------------------------------------------------------------------------
//BOT VALIDATION TRANSFORM CONCAT
//The transform concat is run by botValidationTransformConcat.js. The string to search for in the JSON files is specified in the file and then executed from the command line.

clientName = 'Legend';
 const readBotRulesFromCSV = require('./utils/readBotRulesFromCSV.js');
 const processingStrings = readBotRulesFromCSV('exampleBotRuleList.csv','transform')
  console.log(processingStrings);
const botValidationTransformConcat = require('./botValidationTransformConcat');
botValidationTransformConcat(clientName, processingStrings)


//----------------------------------------------------------------------------------------------------
//HOW TO GET CROSS SITE FIGURES - Unfiltered totals for each rule in each site.

const readBotRulesFromCSV = require('./utils/readBotRulesFromCSV.js');
const downloadFinalBotRuleMetrics = require('./downloadFinalBotRuleMetrics.js');

async function main() {
  const fileName = 'Apr25ValidatedList.csv';
  const segmentsFilePath = await readBotRulesFromCSV(fileName, 'segmentList');
  console.log('Segments file path:', segmentsFilePath);
  
  //UPDATE THE VALUES HERE
  jobName = 'FinalBotRuleMetrics-Apr25'
  fromDate = '2025-07-01'
  toDate = '2025-07-10'
  requestName = 'LegendFinalBotMetricsUnfilteredVisitsByYear'
  interval = 'full'

  // Now you can use the segmentsFilePath
  await downloadFinalBotRuleMetrics(
    segmentsFilePath,
    jobName,
    0, //delay
    fromDate,
    toDate,
    requestName,
    'Legend', //clientName
    interval
  );
}

// Run the main function
main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});

//call downloadFinalBotRuleMetrics

//----------------------------------------------------------------------------------------------------
// Run Final Bot Rule Metrics Transform Concat




//Get a report from each RSID for the excluded rules for the development master bot segment
//I need a new Adobe segment called the development include segment.

