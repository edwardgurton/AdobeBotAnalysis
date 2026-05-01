//add your headers here as a comma delimited string. 
//Headers order: id, dimension, unique_visitors, visits, [additional metrics], fileName, fromDate, toDate
//Note: unique_visitors and visits are always included in reports by default
// let headers = 'id,region,unique_visitors,visits,custom_metric,fileName,fromDate,toDate'
let headers = 'id,variablesgeoregion,unique_visitors,visits,raw_clickouts_linear_7d,raw_clickouts_participation_7d,unique_visit_clickouts_linear_7d,unique_visit_clickouts_participation_7d,fileName,fromDate,toDate'

//new line is added for csv concatenation
if (!headers.endsWith('\n')) {
    headers += '\n';
  }

module.exports = headers;
