// Step One - make relevant updates to runBotRuleCompare.js and run using node from terminal
// Note that this should generally look as far back as the rule validation. The aim is to find new segments which have a high chance of being useful across the full timeline.
// If rerunning for a bot rule then make sure to increment the Version Number
//HINT - THIS WILL COPY FILES FOR ALL TRAFFIC IF THEY MATCH ON DATE + RSID ONLY. SO GENERALLY SET END DATE TO 1st OF NEXT MONTH TO REDUCE DOWNLOADS.

// Step Two - update runBotRuleCompareValidation.js and run using node from terminal

// Step Three - Transform and Concat output


const { transform } = require('lodash');

const readBotRulesFromCsv = require('../utils/readBotRulesFromCsv');

botRulesArray = readBotRulesFromCsv('AdHoc-Bing_compare.csv', 'compare');

console.log(botRulesArray);

const botRuleCompareTransformConcat = require('../botRuleCompareTransformConcat');
// Processing strings are used as strings to match bot rule names in the JSON files and also used for the file output.
async function example1() {
  const clientName = 'Legend';
  //const botRules = ["04-BotCompare-FebMay25-Apuestasdeportivascom-Region-Sachsen"]
  const botRules = botRulesArray
  
  await botRuleCompareTransformConcat(clientName, botRules);
}
example1();

// // ====================================
// const botRuleCompareTransformConcat = require('../botRuleCompareTransformConcat');
// const botRuleCompareTransformConcat = require('./botRuleCompareTransformConcat');

// const botRules = [
//   '0108-Bot-Rule-Casino.us-Domain-chinamobileltdcom',
//   '0109-Bot-Rule-Casino.us-Domain-chinanetcom',
//   '0110-Bot-Rule-Casino.us-Domain-chinaunicomcom'
// ];

// botRuleCompareTransformConcat('Legend', botRules);

// Step Three - use the BotRuleCompare Excel file to analyze the output files.
// In this file, first use DimPivot to identify suspicious dimension features.
// Then analyse those features using the Feature Analysis tab.
// Each dimension feature should get a decision of either : Combine, Own Bot Rule - Run Compare, Own Bot Rule - Straight To Validate, Skip.
// For any "Combines", make a decision on whether you think overlap is likely. We would ideally only have 1 rule if it covers others
// If you think Overlap is likely, then run the segment overlap between any competing segments - name these like 0108a, 0108b etc...
// If you don't think Overlap is likely, then any new rules can be named following the standard bot rule convention - and added to BotRuleValidations - All Outcomes - Rule 70 onwards.xlsx