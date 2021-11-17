const Mfrc522 = require("mfrc522-rpi");
const SoftSPI = require("rpi-softspi");
const CMD = require("mfrc522-rpi/commands");

const softSPI = new SoftSPI({
    clock: 23, // pin number of SCLK
    mosi: 19, // pin number of MOSI
    miso: 21, // pin number of MISO
    client: 24 // pin number of CS
});

var lastCard = "";
var mfrc522 = null;
class RFID {

    constructor(sonos) {
        console.log("Init RFID");
        this.sonos = sonos;
        if (this.sonos === undefined) {
            throw new Error('Could not set sonos in RFID');
        }
        mfrc522 = new Mfrc522(softSPI).setResetPin(22).setBuzzerPin(18);
        var i = 0;
        var interval = setInterval(function () {
            //# reset card
            mfrc522.reset();
            //extend range
            mfrc522.writeRegister(CMD.RFCfgReg, 0x07 << 4);

            //# Scan for cards
            let response = mfrc522.findCard();
            if (!response.status) {
                //console.log("No Card");
                if (i < 3) {
                    i++;
                } else if (i <= 4) {
                    lastCard = "";
                }
                return;
            } else {
                i = 0;
                //console.log("Card detected, CardType: " + response.bitSize);
                response = mfrc522.getUid();
                if (!response.status) {
                    console.log("UID Scan Error");
                    return;
                }
                //# If we have the UID, continue
                const uid = response.data;
                const cardId =
                    uid[0].toString(16) +
                    uid[1].toString(16) +
                    uid[2].toString(16) +
                    uid[3].toString(16);
                if (lastCard !== cardId) {
                    lastCard = cardId;
                    console.log(cardId);

                    //DO Something
                    sonos.play(cardId);
                }
                else {
                    //console.log("Same Card");
                }
            }
        }, 600);
    }

    readRegister (addr){
        return mfrc522.readRegister(addr)
    }
    writeRegister (addr, val){
        mfrc522.writeRegister(addr, val);
    }

};

module.exports = RFID;