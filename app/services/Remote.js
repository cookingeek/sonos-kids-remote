const RPiGPIOButtons = require('rpi-gpio-buttons');
var Sonos = null;
class Remote {

  constructor(sonos) {
    Sonos = sonos;
    console.log("Init Remote");
    let buttons = new RPiGPIOButtons({ pins: [properties.gpio.next, properties.gpio.previous, properties.gpio.volumeDown, properties.gpio.volumeUp] }// use GPIO 17 and 27 for buttons
    );
    buttons.on('pressed', pin => {
      switch (pin) {
        case properties.gpio.next:
          Sonos.next();
          break;
        case properties.gpio.previous:
          Sonos.previous();
          break;
        case properties.gpio.volumeDown:
          Sonos.volumeDown();
          break;
        case properties.gpio.volumeUp:
          Sonos.volumeUp();
          break;
      }
    });

    buttons
      .init()
      .catch(error => {
        console.log('ERROR', error.stack);
        process.exit(1);
      });
  }
};

module.exports = Remote;