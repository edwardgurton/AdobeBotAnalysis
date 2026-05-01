// ============================================================================
// CONFIGURATION - UPDATE THESE VALUES BEFORE RUNNING
// ============================================================================
const toDate = '2025-03-31';           // ← UPDATE THIS DATE before running the script
const segmentCreateDate = '2025-04-04'; // ← UPDATE THIS SEGMENT CREATE DATE
const versionNumber = '3.0';           // ← UPDATE THIS VERSION NUMBER for each run
// ============================================================================

const fs = require('fs');
const path = require('path');
const subtractDays = require('../utils/subtractDays.js');
const retrieveValue = require('../utils/retrieveValue.js');
const downloadBotInvestigationData = require('../downloadBotInvestigationData.js');
const rateLimitManager = require('../utils/RateLimitManager.js');
const legendRsidList = './usefulInfo/Legend/legendReportSuites.txt';

// Function to read the JSON file
function readJsonFile(filePath) {
    const data = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(data);
}

// Function to extract country name from the segment name
function extractCountryName(name) {
    return name.split('=')[1].trim();
}

// Function to read RSID list
function readRsidList(filePath) {
    const data = fs.readFileSync(filePath, 'utf8');
    return data.split('\n').filter(line => line.trim() !== '');
}

// Function to process segments for an RSID
async function processSegmentsForRsid(rsid, toDate, segmentCreateDate, versionNumber) {
    const suiteName = retrieveValue(legendRsidList, rsid, "left");
    const segmentFile = `Legend_${rsid}_variablesgeocountry_segments_${segmentCreateDate}.json`;
    const jsonFilePath = path.join(`config/segmentLists/Legend`, segmentFile);
    
    let segments;
    try {
        segments = readJsonFile(jsonFilePath);
    } catch (error) {
        console.error(`❌ Error reading segment file for ${rsid}: ${jsonFilePath}`, error);
        return;
    }

    const fromDate = subtractDays(toDate, 130);
    
    console.log(`🚀 Processing ${segments.length} segments for RSID: ${rsid} (${suiteName})`);

    const promises = segments.map(async (segment) => {
        const dimSegmentId = segment.id;
        const countryName = extractCountryName(segment.name);
        const rsidValue = retrieveValue(legendRsidList, suiteName, 'right');
        const investigationName = `${suiteName}-${countryName}-FullRun-${versionNumber}`;

        console.log(`🌍 Processing: ${countryName} for RSID: ${rsid}`);

        try {
            await downloadBotInvestigationData(
                500,           // Reduced delay since rate limiting is handled centrally
                fromDate,
                toDate,
                'Legend',      // clientName
                dimSegmentId,
                rsidValue,
                investigationName
            );
            console.log(`✅ Completed: ${countryName} (RSID: ${rsid})`);
        } catch (error) {
            console.error(`❌ Error processing ${countryName} (RSID: ${rsid}):`, error);
        }
    });

    await Promise.all(promises);
    console.log(`✅ All segments processed for RSID: ${rsid}`);
}

// RSID Configuration
//const rsidList = require('./usefulInfo/Legend/rsidListIterateCountries');
const rsidList = ['tribecasinoorg.test'];

// Process all RSIDs with enhanced monitoring
async function processAllRsids() {
    console.log(`📊 Processing ${rsidList.length} RSIDs with segments`);
    console.log(`📅 Date range: ${subtractDays(toDate, 130)} to ${toDate}`);
    console.log(`🏷️  Segment create date: ${segmentCreateDate}`);
    console.log(`🔢 Version: ${versionNumber}`);
    
    // Status reporting interval
    const statusInterval = setInterval(() => {
        const status = rateLimitManager.getStatus();
        if (status.queueLength > 0 || status.activeRequests > 0) {
            console.log(`📈 Status - Queue: ${status.queueLength}, Active: ${status.activeRequests}${status.isPaused ? `, Paused until: ${status.pauseUntil}` : ''}`);
        }
    }, 30000); // Every 30 seconds
    
    try {
        for (const rsid of rsidList) {
            console.log(`\n🎯 Starting processing for RSID: ${rsid}`);
            await processSegmentsForRsid(rsid, toDate, segmentCreateDate, versionNumber);
            console.log(`🎉 Finished processing for RSID: ${rsid}`);
            
            // Small delay between RSIDs to prevent overwhelming
            if (rsidList.indexOf(rsid) < rsidList.length - 1) {
                console.log(`⏳ Brief pause before next RSID...`);
                await new Promise(resolve => setTimeout(resolve, 2000));
            }
        }
        
        console.log("🎉 All RSIDs have been processed successfully!");
    } finally {
        clearInterval(statusInterval);
    }
}

// Run the main process
processAllRsids().catch(error => {
    console.error("💥 An error occurred in the main process:", error);
});