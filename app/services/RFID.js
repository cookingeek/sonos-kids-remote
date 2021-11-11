var rc522 = require("rc522");

class RFID {

    constructor() {
        console.log("test");
        rc522(function(rfidSerialNumber){
            console.log(rfidSerialNumber);
        });
      }
};

module.exports = RFID;