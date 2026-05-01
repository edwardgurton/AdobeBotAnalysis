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
LegendReportSuiteUpdater(false, 1000, 1000, '2025-03-01','2025-06-30');

// 2) Execute BotInvestigationGenerateCountrySegments
//          Why?
//              Because for our large sites it creates a list of country x site combinations above a given threshold and generates an object for iterating through these.
//          Why do that? 
//              Because for very large sites we investigate specific countries for spikes or irregular features which might otherwise be too small of we looked at all site data.

const BotInvestigationGenerateCountrySegments = require('../BotInvestigationGenerateCountrySegments');

// Include virtual report suites (true/false), optional fromDate in format YYYY-MM-DD, optional toDate in format YYYY-MM-DD
//      a) Choose appropriate threshold (100k is recommended)
//      b) Update date at end to the end of the period you're investigating
BotInvestigationGenerateCountrySegments(3000,"2025-10-11","2025-11-09")

// 3) Execute iterateRsidCountriesBotInvestigation (EXECUTE IN TERMINAL)
//      
//      Why?
//          This will download all the necessary investigation data for the second round (investigations for any countries in a report suite with more than the threshold of visits)
//
//     How/
//         First edit the config at the bottom of the file to select the appropriate report suites and countries to investigate.
//          Open terminal and run the following command: caffeinate node iterateRsidCountriesBotInvestigation.js

//  4) Validate that all files were successfully downloaded.

//rememebr to add the options from

const validateBotInvestigationTypeTwo = require('../validateBotInvestigationTypeTwo');

validateBotInvestigationTypeTwo(4.7, '2026-01-19', {
    subtractDaysValue: 90,
    rsidCleanNames: ['Oddspediacom'],
    countries: ['Singapore', 'Hong Kong SAR of China'],
    redownloadMissing: true
});

// 5) Transform Concat all the downloaded files.
// This script is mostly fit for purpose. We can just

const botInvestigationTransformConcat = require('../botInvestigationTransformConcat')

//Before running, ensure that the file is pointing towards the rsid list. The script will still work with the full list - but will be much slower.
//Investigation Round should be string specified when calling iterateRsids. The downloadBatch is either 1 for the single country downloads, 2 for the country x rsid combinations.
botInvestigationTransformConcat("4.7",2)