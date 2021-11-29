const Gpio = require('onoff').Gpio;
const beeper = new Gpio(17, 'out');

class Beeper {

    constructor() {

        console.log("Init Beeper");

    }

    beep(){
        beeper.writeSync(1);
        setTimeout(function(){
            beeper.writeSync(0);
        }, 300)
    }
};

module.exports = Beeper;