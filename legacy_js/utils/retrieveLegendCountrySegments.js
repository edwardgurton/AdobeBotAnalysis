const countrySegmentLookup = require('../usefulInfo/Legend/countrySegmentLookup');

/**
 * Retrieves the segmentId for a given DimValueName
 * @param {string} dimValueName - The dimension value name to look up
 * @returns {string|null} The corresponding segmentId or null if not found
 */
function getSegmentIdByDimValueName(dimValueName) {
  // Handle case where lookup data doesn't exist
  if (!countrySegmentLookup || !Array.isArray(countrySegmentLookup)) {
    console.warn('countrySegmentLookup data is not available or not an array');
    return null;
  }

  // Find the entry with matching DimValueName
  const entry = countrySegmentLookup.find(item => 
    item.DimValueName === dimValueName
  );

  return entry ? entry.SegmentId : null;
}

/**
 * Case-insensitive version of the lookup function
 * @param {string} dimValueName - The dimension value name to look up (case-insensitive)
 * @returns {string|null} The corresponding SegmentId or null if not found
 */
function getSegmentIdByDimValueNameIgnoreCase(dimValueName) {
  if (!countrySegmentLookup || !Array.isArray(countrySegmentLookup)) {
    console.warn('countrySegmentLookup data is not available or not an array');
    return null;
  }

  const entry = countrySegmentLookup.find(item => 
    item.DimValueName && item.DimValueName.toLowerCase() === dimValueName.toLowerCase()
  );

  return entry ? entry.SegmentId : null;
}

/**
 * Gets all available DimValueNames for reference
 * @returns {string[]} Array of all available DimValueNames
 */
function getAllDimValueNames() {
  if (!countrySegmentLookup || !Array.isArray(countrySegmentLookup)) {
    return [];
  }

  return countrySegmentLookup.map(item => item.DimValueName).filter(Boolean);
}

module.exports = {
  getSegmentIdByDimValueName,
  getSegmentIdByDimValueNameIgnoreCase,
  getAllDimValueNames
};