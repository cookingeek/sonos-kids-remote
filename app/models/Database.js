/**
 *
 */
'use strict'

const loki = require('lokijs/src/lokijs.js');

var db = new loki('db/' + properties.db.filename, {
  autoload: true,
  autosave: true
});

class Database {
  constructor() {
    this.entries = db.getCollection("entries");
    if (this.entries === null) {
      this.entries = db.addCollection("entries");
      //create dummy line
      this.entries.insert({ _card: "d7deb4e", source: "local", type: "file", id: "dean.mp3" }
      );
    }
  }

  create(data) {
    this.entries.insert(data);
  }

  update(entry) {
    this.entries.update(entry);
  }

  remove(entry) {
    this.entries.remove(entry);
  }

  findById(id) {
    return this.entries.find({
      _card: id
    });
  }

  findAll(){
    return this.entries.find();
  }
}

module.exports = Database;