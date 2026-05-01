// Production mode - process all rows
const createSegmentFromList = require('../createSegmentFromList');

const list = 'Oddspedia-AdHoc-Jan26-RoundFive-MoneyPillar.csv';  // .csv extension is optional
createSegmentFromList(list, { 
    userIds: ['200419062'] 
});

//My user Id = 200419062

//Test mode - save JSON for a specific row
//createSegmentFromList(list, { testMode: true, testRow: 1 });

// const saveSegment = require('../utils/saveSegment')
// saveSegment('s3938_6949564662fb9877ebbad9bd','Legend')
