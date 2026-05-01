const addRequestDetails = require('./utils/addRequestDetails');
const getAdobeTable = require('./utils/getAdobeTable');
const extractValueId = require('./utils/extractValueId');

async function buildSegmentsFromDimension(clientName, dimensionName, segments = []) {
  // Create a request name for this dimension
  const requestName = `SegmentsBuilder${dimensionName.replace(/[/.]/g, '')}`;
  
  console.log(`Building segments for dimension: ${dimensionName}`);
  console.log(`Request name: ${requestName}`);
  console.log(`Using segments: ${segments.length > 0 ? segments.join(', ') : 'none'}`);

  // Call addRequestDetails with the segments array
  await addRequestDetails(clientName, requestName, dimensionName, segments);

  // Calculate fromDate and toDate (last 31 days)
  const today = new Date();
  const fromDate = new Date(today);
  fromDate.setDate(today.getDate() - 31);

  const formatDate = (date) => date.toISOString().split('T')[0];

  const fromDateStr = formatDate(fromDate);
  const toDateStr = formatDate(today);

  console.log(`Date range: ${fromDateStr} to ${toDateStr}`);

  // Clean the request name the same way addRequestDetails does
  const cleanedRequestName = requestName.replace(/[^a-zA-Z0-9]/g, '');

  console.log(`Cleaned request name: ${cleanedRequestName}`);

  // For getAdobeTable, use the first segment if available (for backward compatibility)
  const dimSegmentId = segments.length > 0 ? segments[0] : undefined;

  // Call getAdobeTable with the cleaned request name
  const adobeTableResponse = await getAdobeTable(
    fromDateStr,
    toDateStr,
    cleanedRequestName,
    clientName,
    dimSegmentId  // Use first segment for filtering
  );

  console.log('Adobe table response received');

  // Extract value ID from the response
  const result = await extractValueId(adobeTableResponse);
  console.log(`Extracted ${result?.length || 0} value-ID pairs`);
  
  return result;
}

module.exports = buildSegmentsFromDimension;