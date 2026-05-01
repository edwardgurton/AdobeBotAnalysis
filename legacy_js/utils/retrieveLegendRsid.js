const fs = require('fs');
const path = require('path');
const legendRsidLookup = './usefulInfo/Legend/legendReportSuites.txt'
const retrieveValue = require('./retrieveValue');

function retrieveLegendRsid(suite) {

return retrieveValue(legendRsidLookup, suite, 'right')
}

module.exports = retrieveLegendRsid;