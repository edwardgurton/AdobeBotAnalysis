//STEP ONE - DOWNLOAD DATA FOR BOT RULES
// If you need to use Caffeinare then update downloadBotRuleValidationData and execute from the terminal
//Update the botRulesList, fromDate, and toDate variables as needed for your bot validation.

const processBotRules = require('../downloadBotRuleValidationData').processBotRules;
const readBotRulesFromCSV = require('../utils/readBotRulesFromCSV');

botRulesList = readBotRulesFromCSV('FebMay25RoundFour_validate.csv','download') //update the file name as needed
fromDate = '2024-02-01'; // Update the fromDate as needed, the typical approach is past 24 months
toDate = '2026-02-01' //Update the toDate, as the date ranges use midnight, then use the first day of the next month to ensure the full month is included in the data.
clientName = 'Legend';

processBotRules(botRulesList, fromDate, toDate, clientName)

//STEP TWO - VALIDATE THE DOWNLOAD

async function main() {
const validateMultipleBotRules  = require('../validateBotValidationDownload').validateMultipleBotRules;
fromDate = '2024-02-01'; // Update the fromDate as needed, the typical approach is past 24 months
toDate = '2026-02-01' //Update the toDate, as the date ranges use midnight, then use the first day of the next month to ensure the full month is included in the data.
clientName = 'Legend';
const readBotRulesFromCSV = require('../utils/readBotRulesFromCSV');
botRulesList = readBotRulesFromCSV('Oddspedia-AdHoc-Jan26-RoundFive_validate.csv','download') //update the file name as needed
options = {}     //Use Options object to pass additional parameters if needed, such as Full Run Version or which RSID list to use.
await validateMultipleBotRules(fromDate, toDate, botRulesList, options)
}
main()

//STEP THREE - TRANSFORM AND CONCAT THE DATA
const botValidationTransformConcat = require('../botValidationTransformConcat');

const readBotRulesFromCSV = require('../utils/readBotRulesFromCSV');
botRulesList = readBotRulesFromCSV('Oddspedia-AdHoc-Jan26-RoundFive_validate.csv','transform') //update the file name as needed

botValidationTransformConcat('Legend',botRulesList)
