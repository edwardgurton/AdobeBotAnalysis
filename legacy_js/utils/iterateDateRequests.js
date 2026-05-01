const downloadAdobeTable = require('../downloadAdobeTable');
const generateFromToDates = require('./generateFromToDates')

async function iterateDateRequests(delay = 0, fromDate, toDate, requestName, clientName, interval = 'day', dimSegmentID = undefined, rsid="default", fileNameExtra = undefined) {
    console.log(`Starting date iteration from ${fromDate} to ${toDate} with interval: ${interval}`);
    
    if (interval === 'full') {
        // For full interval, make a single request for the entire date range
        console.log(`Processing full range: ${fromDate} to ${toDate}`);
        
        try {
            await downloadAdobeTable(fromDate, toDate, requestName, clientName, dimSegmentID, rsid, fileNameExtra);
        } catch (error) {
            console.error(`Error downloading data for full range ${fromDate} to ${toDate}:`, error);
        }
        
    } else if (interval === 'month') {
        // For month interval, work with string dates to avoid timezone issues
        const startYear = parseInt(fromDate.split('-')[0]);
        const startMonth = parseInt(fromDate.split('-')[1]) - 1; // Convert to 0-based
        const endYear = parseInt(toDate.split('-')[0]);
        const endMonth = parseInt(toDate.split('-')[1]) - 1; // Convert to 0-based
        
        let currentYear = startYear;
        let currentMonth = startMonth;
        
        while (currentYear < endYear || (currentYear === endYear && currentMonth <= endMonth)) {
            // Create month strings
            const monthStr = String(currentMonth + 1).padStart(2, '0'); // Convert back to 1-based
            const yearStr = String(currentYear);
            
            // Get days in this month
            const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
            
            // Create from and to dates for this month
            let requestFromDate = `${yearStr}-${monthStr}-01`;
            let requestToDate = `${yearStr}-${monthStr}-${String(daysInMonth).padStart(2, '0')}`;
            
            // Adjust first month if fromDate is not the 1st
            if (currentYear === startYear && currentMonth === startMonth) {
                requestFromDate = fromDate;
            }
            
            // Adjust last month if toDate is not the last day
            if (currentYear === endYear && currentMonth === endMonth) {
                requestToDate = toDate;
            }
            
            console.log(`Processing month: ${requestFromDate} to ${requestToDate}`);
            
            try {
                await downloadAdobeTable(requestFromDate, requestToDate, requestName, clientName, dimSegmentID, rsid, fileNameExtra);
            } catch (error) {
                console.error(`Error downloading data for month ${requestFromDate}:`, error);
            }
            
            // Move to next month
            currentMonth++;
            if (currentMonth > 11) {
                currentMonth = 0;
                currentYear++;
            }
            
            // Add delay if specified
            if (delay > 0) {
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        
    } else if (interval === 'day') {
        // For day interval, use the original logic with generateFromToDates
        let currentDate = new Date(fromDate + 'T00:00:00.000Z'); // Force UTC to avoid timezone issues
        const endDate = new Date(toDate + 'T23:59:59.999Z'); // Force UTC
        
        while (currentDate <= endDate) {
            const formattedCurrentDate = currentDate.toISOString().slice(0, 10);
            const {fromDate: genFromDate, toDate: genToDate} = generateFromToDates(formattedCurrentDate, 'fixed', interval);
            
            console.log(`Processing day: ${genFromDate} to ${genToDate}`);
            
            try {
                await downloadAdobeTable(genFromDate, genToDate, requestName, clientName, dimSegmentID, rsid, fileNameExtra);
            } catch (error) {
                console.error(`Error downloading data for day ${formattedCurrentDate}:`, error);
            }
            
            // Move to next day
            currentDate.setUTCDate(currentDate.getUTCDate() + 1);
            
            // Add delay if specified
            if (delay > 0) {
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        
    } else {
        throw new Error("Invalid interval. Use 'day', 'month', or 'full'.");
    }
    
    console.log(`Completed date iteration for ${requestName}`);
}

module.exports = iterateDateRequests