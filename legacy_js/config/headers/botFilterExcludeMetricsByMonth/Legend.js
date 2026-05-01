//add your headers here as a comma delimited string. Remember that the last 5 or 6 will be dimension, id, fileName, fromDate, toDate
// let headers = 'region,item_id,visits'
let headers = 'id,month,unique_visitors,visits,raw_clickouts,engaged_visits,engagement_rate,First_Time_Visits,Total_Seconds_Spent,Page_Views,fileName,requestName,botRuleName,rsidName'

//new line is added for csv concatenation
if (!headers.endsWith('\n')) {
    headers += '\n';
  }

module.exports = headers;
