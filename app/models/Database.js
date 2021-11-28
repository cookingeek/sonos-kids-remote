/**
 *
 */
'use strict'

const loki = require('lokijs/src/lokijs.js');
class Database {

  constructor() {
    var that = this;
    that.db = new loki('db/' + properties.db.filename, {
      autoload: true,
      autoloadCallback: loadHandler,
      autosave: true
    });
    function loadHandler() {
      that.entries = that.db.getCollection("entries")
      if (that.entries == null) {
        that.entries = that.db.addCollection("entries");
      }
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

  findAll() {
    return this.entries.find();
  }
}

module.exports = Database;