//HOW TO USE

//For each step, select all the text and press Ctrl + Alt + N to execute. Most steps will execute in 5 minutes. However the two downloading steps will take many hours.
//You will probably need

// 0) Update the Read Write Settings. This will decide where all of the files are saved.

// 1) Execute legendReportSuiteUpdater.
//         Why?
//          Because it checks for any new report suites that have been created and then runs a report for the specified dates to
//          And as an output, it generates a list of all report suites which have met the threshold.

const LegendReportSuiteUpdater = require('../legendReportSuiteUpdater');

// Include virtual report suites (true/false), investigation threshold, validation threshold, optional fromDate in format YYYY-MM-DD, optional toDate in format YYYY-MM-DD
//      a) Choose appropriate threshold
//      b) Update date at end to the end of the period you're investigating
LegendReportSuiteUpdater(false, 1000, 1000, '2025-11-01','2025-12-31');

// 2) Execute BotInvestigationGenerateCountrySegments
//          Why?
//              Because for our large sites it creates a list of country x site combinations above a given threshold and generates an object for iterating through these.
//          Why do that? 
//              Because for very large sites we investigate specific countries for spikes or irregular features which might otherwise be too small of we looked at all site data.

const BotInvestigationGenerateCountrySegments = require('../BotInvestigationGenerateCountrySegments');

// Include virtual report suites (true/false), optional fromDate in format YYYY-MM-DD, optional toDate in format YYYY-MM-DD
//      a) Choose appropriate threshold (100k is recommended)
//      b) Update date at end to the end of the period you're investigating
BotInvestigationGenerateCountrySegments(100000,"2025-02-01","2025-05-01")

// 3) Execute iterateRsidsBotInvestigation (EXECUTE IN TERMINAL)
//      Why?
//          This will download all the necessary investigation data for the first round (one investigation per RSID).
//
//     How/

//
//     How long?
//      This may take ~24 hours, depending on the threshold you set.

// 4) Run the validator to check if any files were missed
//      Why?
//          This will check that all required reports were downloaded in Step Three. It will then download any missed reports.  
//          It's recommended to run this again if the first sweep required any additional downloads          

const validateBotInvestigationTypeOne = require('../validateBotInvestigationTypeOne')

validateBotInvestigationTypeOne("4.4","2025-08-31",{
    dateRangeMode: 'fixedFromDate', // 'fixedFromDate' or 'subtractDays'
    fromDate: '2025-05-01',
    // daysToSubtract: 130,
});


// 5) botInvestigationTransformConcat


const botInvestigationTransformConcat = require('../botInvestigationTransformConcat')

//Investigation Round should be string specified when calling iterateRsids. The downloadBatch is either 1 for the single country downloads, 2 for the country x rsid combinations.
botInvestigationTransformConcat("4.4",1)


// 6) Execute iterateRsidCountriesBotInvestigation (EXECUTE IN TERMINAL)
//      Why?
//          This will download all the necessary investigation data for the second round (investigations for any countries in a report suite with more than the threshold of visits)
//
//     How/

const config = {
        toDate: '2025-05-31',
        mode: 'subtractDays', // Use 'fixedDate' if you want to set a specific fromDate. subTractDays to subtract from toDate.
        fromDate: '2025-01-01', // If mode is 'fixedDate', set the specific fromDate here
        subtractDaysValue: 130,  // Will calculate fromDate as toDate - 130 days    
        investigationRound: 4.0, // USed
        rsidCountriesListPath: './usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js',
        enableStatusReporting: true,
        statusReportingInterval: 30000  // Report status every 30 seconds
    };
const processBotInvestigation = require('../iterateRsidCountriesBotInvestigation');
processBotInvestigation(config);



//
//     How long?
//      This may take ~24 hours, depending on the threshold you set.

