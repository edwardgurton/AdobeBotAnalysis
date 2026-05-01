//The `generateFromToDates` function helps you get two dates based on a given starting date.\\n\\n
//You give it a date and tell it whether this date is a fixed date like "2024-08-06" or a number of days before today (like 5 days ago).\\n\\n
//The function then gives you the starting date and the next day.\\n\\n
//For example, if you input "2024-08-06," it will give you "2024-08-06" and "2024-08-07".\\n\\n
//If you say it's 5 days ago, it will calculate the dates 5 days ago and the next day.\\n\\n
//The interval argument determines whether the endDate will be the following day, or the following month.


function generateFromToDates(inputDate, inputDateType, interval) {
  // Function to get the date n days ago
  function getDateNDaysAgo(n) {
    const today = new Date();
    today.setDate(today.getDate() - n);

    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');

    const formattedDate = `${year}-${month}-${day}T00:00:00`;
    return formattedDate;
  }

  // Ensure that inputDateType is either 'fixed' or 'relative'
  if (inputDateType !== 'fixed' && inputDateType !== 'relative') {
    console.log('inputDateType must be fixed or relative. You entered:', inputDateType);
    return; // Early exit if inputDateType is invalid
  }

  let inputDateTime;

  if (inputDateType === 'fixed') {
    // Check if the inputDate is in the correct format "YYYY-MM-DD"
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(inputDate)) {
      throw new Error("Invalid input date format. Please provide a date in the 'YYYY-MM-DD' format.");
    }

    // Parse the inputDate string into a Date object
    inputDateTime = new Date(inputDate + 'T12:00:00'); // Set the time to midnight
    if (isNaN(inputDateTime.getTime())) {
      throw new Error("Failed to parse input date into a valid Date object.");
    }
  }

  if (inputDateType === 'relative') {
    inputDateTime = new Date(getDateNDaysAgo(inputDate));
    if (isNaN(inputDateTime.getTime())) {
      throw new Error("Failed to parse input date into a valid Date object.");
    }
  }

  //console.log('inputDateTime:', inputDateTime);

  // Clone the inputDateTime to create the toDate
  const toDate = new Date(inputDateTime);

  if (interval === 'day') {
    toDate.setDate(inputDateTime.getDate() + 1); // Add one day
  } else if (interval === 'month') {
    toDate.setMonth(inputDateTime.getMonth() + 1); // Add one month
  } else {
    throw new Error("Invalid interval. Please provide 'day' or 'month' as the interval.");
  }

  const fromDate = inputDateTime.toISOString().slice(0, 10); // Format fromDate as 'YYYY-MM-DD'
  const toDateFormatted = toDate.toISOString().slice(0, 10); // Format toDate as 'YYYY-MM-DD'

  return {
    fromDate,
    toDate: toDateFormatted,
  };
}

module.exports = generateFromToDates;

