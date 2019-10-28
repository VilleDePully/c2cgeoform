import { Circle, Fill, Stroke, Style, Icon } from 'ol/style.js'

const defaultIconUrl =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAMAAAC6V+0/AAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAABm1BMVEUAAADdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPYLi7dMzPcMjLdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzPdMzP///+sruHMAAAAh3RSTlMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEhIANcHBNgyxsw1b9/hdGMnKGXf++c75/nkq3eIpKd4rBJTgHZUEQO3tQQywsQxa9+Ad91sYyOVDyRh2/v3v/ncp3frd3SkEkuMvkwRI6uQ76kjC/OjC9/eP19/e148GHCMjHAYUgpGvAAAAAWJLR0SIa2YWWgAAAAd0SU1FB+MKGAomNRvjZowAAAEBSURBVBjTY2CAAEZFJWUVJgYUwMyiqqauwcqGIsiuqdXerq3DgSzGyaGr196ub8DFjSTIY2jUDgTGJuwIMV4+UzNzCwtLK2t+AZiYoJCNbbudvYNdu6MTjzDMFmeX9nZXNzfX9nZ3DxGImCi7pxdM0NuHRwwsKO7r1w4TbPcPkACJSfIEBgF5wSEhwUAqNExKGigoEx4Bck5kVFQkiI6OkWVgYJWLjQNx4hMS4kF0YpK8AgN7cgqI3Z6alpYKZqRnsDBkZoGZ7dk5OdkQVm4eQ34BhFlYVFQIYRWXMJRCWO1l5eVlUGYFQ2U7BqhiqK6prUMBtfUNDI1NzS0ooLm1DQBCY3WJfMK7sQAAACV0RVh0ZGF0ZTpjcmVhdGUAMjAxOS0xMC0yNFQxMDozODo1My0wNDowMIZxXTkAAAAldEVYdGRhdGU6bW9kaWZ5ADIwMTktMTAtMjRUMTA6Mzg6NTMtMDQ6MDD3LOWFAAAAAElFTkSuQmCC'

export function getDefaultStyle() {
  return new Style({
    stroke: new Stroke({
      color: 'blue',
      width: 3,
    }),
    fill: new Fill({
      color: 'rgba(0, 0, 255, 0.1)',
    }),
    image: new Circle({
      radius: 6,
      stroke: new Stroke({
        width: 1.5,
        color: 'rgba(0, 0, 255, 1)',
      }),
      fill: new Fill({
        color: 'rgba(0, 0, 255, 0.4)',
      }),
    }),
  })
}

export function getStyleFunction(options) {
  return feature =>
    new Style({
      image: new Icon({
        anchorXUnits: 'fraction',
        anchorYUnits: 'pixels',
        src: feature.get('icon') || defaultIconUrl,
        opacity: options.opacity || 1,
      }),
    })
}
