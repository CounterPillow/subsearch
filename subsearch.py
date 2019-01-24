#!/usr/bin/env python3
import subprocess
import json
import os
import random

import pysubs2
import attr
import whoosh.fields
import whoosh.index
import whoosh.qparser
import click

@attr.s
class FFmpeg:
    cmd = attr.ib()

    def run(self, *args):
        #return subprocess.check_output([cmd, '-nostdin', '-y'] + args)
        return subprocess.check_output([self.cmd, '-nostdin', '-y', '-hide_banner', '-loglevel', 'panic'] + list(args))

    def read_subs(self, path):
        out = self.run('-i', path, '-f', 'ass', '-')
        return pysubs2.SSAFile.from_string(out.decode('utf-8'))

    def get_image(self, path, start, time):
        self.run('-ss', str(start / 1000), '-i', path, '-copyts', '-ss', str(time / 1000), '-filter:v', "subtitles='{}'".format(path.replace("'", r"\'")), '-vframes', '1', '-f', 'image2', 'out.png')

@attr.s
class Result:
    path = attr.ib()
    content = attr.ib()
    start = attr.ib()
    end = attr.ib()

    @property
    def midpoint(self):
        return (self.start + self.end) / 2

@attr.s
class Database:
    path = attr.ib()
    ix = attr.ib()
    relative = attr.ib()
    
    @classmethod
    def create(cls, path, relative=False):
        schema = whoosh.fields.Schema(
            path=whoosh.fields.ID(stored=True),
            start=whoosh.fields.NUMERIC(stored=True),
            end=whoosh.fields.NUMERIC(stored=True),
            content=whoosh.fields.TEXT(stored=True),
        )
        config = dict(
            relative=relative,
        )
        os.makedirs(path, exist_ok=True)
        ix = whoosh.index.create_in(path, schema)
        with open(os.path.join(path, 'subsearch-config.json'), 'w') as f:
            json.dump(config, f)
        return cls(path, ix, relative)

    @classmethod
    def open(cls, path):
        ix = whoosh.index.open_dir(path)
        with open(os.path.join(path, 'subsearch-config.json')) as f:
            config = json.load(f)
        return cls(path, ix, **config)

    def search(self, query, **kwargs):
        q = whoosh.qparser.QueryParser("content", self.ix.schema).parse(query)
        with self.ix.searcher() as searcher:
            for r in searcher.search(q, **kwargs):
                d = dict(r)
                d['path'] = os.path.normpath(os.path.join(self.path, d['path']))
                yield Result(**d)

    def add_recursive(self, ff, path, **kwargs):
        for d in sorted(os.listdir(path)):
            full = os.path.join(path, d)
            self.add(ff, full, **kwargs)

    def add(self, ff, path, report=None, relative=None):
        if relative is None:
            relative = self.relative
        if os.path.isdir(path):
            return self.add_recursive(ff, path, report=report, relative=relative)

        realpath = path
        if relative:
            path = os.path.normpath(os.path.relpath(path, self.path))
        else:
            path = os.path.abspath(path)
        if report:
            report(path)

        subs = ff.read_subs(realpath)
        writer = self.ix.writer()
        for ev in subs.events:
            if ev.is_comment:
                continue
            writer.add_document(path=path, start=ev.start, end=ev.end, content=ev.plaintext)
        writer.commit()

@click.group()
def cli():
    pass

@cli.command()
@click.option('--relative/--absolute', '-r/-a', is_flag=True)
@click.argument('dbpath', type=click.Path())
def init(dbpath, relative):
    Database.create(dbpath, relative=relative)

@cli.command()
@click.option('--relative/--absolute', '-r/-a', is_flag=True, default=None)
@click.argument('dbpath', type=click.Path())
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def add(dbpath, paths, relative):
    db = Database.open(dbpath)
    ff = FFmpeg('ffmpeg')
    def report(s):
        click.echo('adding: {}'.format(s))
    for path in paths:
        db.add(ff, path, report=report, relative=relative)

@cli.command()
@click.argument('dbpath', type=click.Path())
@click.argument('query', nargs=-1)
def search(dbpath, query):
    query = ' '.join(query)
    db = Database.open(dbpath)
    ff = FFmpeg('ffmpeg')
    r = list(db.search(query))
    if r:
        ev = random.choice(r)
        print(ev.path)
        print(ev.content)
        ff.get_image(ev.path, ev.start, ev.midpoint)

if __name__ == "__main__":
    cli()