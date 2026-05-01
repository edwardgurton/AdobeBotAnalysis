//STEP ONE: REQUEST AND DOWNLOAD JSON FILES FROM THE ADOBE

const downloadBotInvestigationData = require('../downloadBotInvestigationData');
const downloadBotInvestigationUnfilteredData = require('../downloadBotInvestigationUnfilteredData');

//select the reportsuite here
const suite = 'Casinoorg'
const retrieveLegendRsid = require('../utils/retrieveLegendRsid');
const rsid = retrieveLegendRsid(suite)
console.log(rsid)

//to add a country segment, use these four lines and comment out the dimSegmentId line below

// const segmentInfo = 'Canada'
// const { getSegmentIdByDimValueName, getSegmentIdByDimValueNameIgnoreCase } = require('../utils/retrieveLegendCountrySegments');
// const dimSegmentId = getSegmentIdByDimValueNameIgnoreCase(segmentInfo)
// console.log(dimSegmentId)

//to add a custom segment, enter the segment ID here and comment out the 
const dimSegmentId = undefined //'s3938_68946a1bee429545a14df753'; // Example segment ID, replace with actual segment ID if needed
const countryName = 'AllCountries-Unfiltered'; // Use this variable to input helpful information into the bot investigation prefix. This will be used to group your files together later.

//Update the dates here.Lookback window should generally by 31 for a one-off investigation, but can be longer if needed.
//For the fromDate, you have a choice between using a fixed date or subtratcing X days from the fromDate.
const toDate = '2025-08-31';
const subtractDays = require('../utils/subtractDays');
const fromDate = subtractDays(toDate,61)

//run these two lines and note value for next step
const investigationPrefix = `botInvestigation-${suite}-${countryName}-${toDate}`;
console.log("investigationPrefix: ", investigationPrefix)

//downloadBotInvestigationData(0,fromDate, toDate, 'Legend',dimSegmentId,rsid,investigationPrefix)
downloadBotInvestigationUnfilteredData(0,fromDate, toDate, 'Legend',dimSegmentId,rsid,investigationPrefix) //UNFILTERED DATA DOWNLOAD


//ONE-OFF VALDATION 



//---------------------------------------------------------------------------------------------------

//RUN TRANSFORM CONCAT FOR ONE-OFF

const botInvestigationTransformConcat = require('../botInvestigationTransformConcat')
botInvestigationTransformConcat("V0",3,{
    toDate: '2025-08-31',
    subtractDays: 61,
    botInvestigationPrefix: 'botInvestigation-Casinoorg-AllCountries-Unfiltered-2025-08-31'
});
