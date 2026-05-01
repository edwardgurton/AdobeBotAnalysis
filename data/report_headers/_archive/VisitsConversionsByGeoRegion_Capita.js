//add your headers here as a comma delimited string. Remember that the last 5 or 6 will be dimension, id, [segmentId (if using a dimSegment)], fileName, fromDate, toDate
// let headers = 'region,item_id,visits'
let headers='id,geo_region,visits,modelledOnsiteApps,registrationStarts,fileName,fromDate,toDate'

//new line is added for csv concatenation
if (!headers.endsWith('\n')) {
    headers += '\n';
  }

module.exports = headers;
