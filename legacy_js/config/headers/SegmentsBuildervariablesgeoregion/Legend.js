//add your headers here as a comma delimited string. Remember that the last 5 or 6 will be dimension, id, fileName, fromDate, toDate
// let headers = 'region,item_id,visits'
let headers = 'id,variablesgeoregion,unique_visitors,visits,fileName,fromDate,toDate'

//new line is added for csv concatenation
if (!headers.endsWith('\n')) {
    headers += '\n';
  }

module.exports = headers;
