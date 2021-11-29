module.exports = {
    name: "Jakobs Sonos Controller",
    sonos: {
        base: 'Move',
        localmusic: {
            port: '3000',
            musicfolder: 'localmusic',
            protocol: 'http',
            hostname: 'jakobsjukebox'
        }
    },
    webserver: {
        interface: 'wlan0'
        //interface: 'en0'
    },
    gpio: {
        next: '19',
        previous: '6',
        volumeUp: '13',
        volumeDown: '5',
        led: '',
        beeper: '17'
    },
    db:{
        filename: 'database.db'
    }
};