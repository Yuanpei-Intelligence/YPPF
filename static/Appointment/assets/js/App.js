var App = function() {
  this.id = ('page' + Math.random()).replace('0.','-');
  this.el = $('<section id="'+this.id+'"></section>');
  this.page = [];
  $('body').append(this.el);
  // this.el.fullPage();

  this.addPage = function(name, title, cfg) {
    var cfg = cfg || {};
    var page = $('<div class="section page"></div>');
    if (name != undefined) {
      page.addClass('page-' + name);
    }
    if (title != undefined) {
      page.append($('<h2 class="page__title">'+ title +'</h2>'))
      // page.text(title);
    }
    // cfg.background && page.find('.page__inner').css({'background': 'url(' + cfg.background + ')'});
    cfg.css && page.css(cfg.css);
    cfg.bgBack && page.append($('<div class="bg-back"></div>')).find('.bg-back').css({
      'background': 'url(' + cfg.bgBack + ') no-repeat',
      'background-size': 'cover'
    });
    cfg.bgLight && page.append($('<div class="bg-light"></div>')).find('.bg-light').css({
      'background': 'url(' + cfg.bgBack + ') no-repeat',
      'background-size': 'cover'
    });
    this.el.append(page);
    this.page.push(page);
    return this;
  }

  return this;
}
