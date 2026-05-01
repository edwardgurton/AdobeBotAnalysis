const getAdobeUsers = require('../utils/getAdobeUsers.js')

getAdobeUsers('Legend');

const shareAdobeSegment = require('../utils/shareAdobeSegment.js');

segmentId = 's3938_695cf924e727080395ef7989'
userId = '200419062'
shareAdobeSegment(segmentId, userId, 'Legend')