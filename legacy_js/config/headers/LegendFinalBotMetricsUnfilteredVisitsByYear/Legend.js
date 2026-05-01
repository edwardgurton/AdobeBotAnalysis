//only use this for final bot rule metrics as it contains custom headers
//add your headers here as a comma delimited string. 
//Headers order: id, dimension, unique_visitors, visits, [additional metrics], fileName, fromDate, toDate
//Note: unique_visitors and visits are always included in reports by default
// let headers = 'id,region,unique_visitors,visits,custom_metric,fileName,fromDate,toDate'
let headers = 'id,variablesdaterangeyear,unique_visitors,visits,fileName,botRuleName,rsidCleanName,fromDate,toDate'

//new line is added for csv concatenation
if (!headers.endsWith('\n')) {
    headers += '\n';
  }

module.exports = headers;
