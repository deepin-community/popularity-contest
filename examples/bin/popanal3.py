#!/usr/bin/python3
#
# Read Debian popularity-contest submission data on stdin and produce
# some statistics about it.
#
import sys, string, time, glob, lzma

mirrorbase = "/srv/mirrors/debian"
stable_version = "1.71"

def ewrite(s):
    sys.stderr.write("%s\n" % s)

class Vote:
    yes = 0
    old_unused = 0
    too_recent = 0
    empty_package = 0

    def vote_for(vote, package, entry):
        now = time.time()
        if entry.atime == 0:  # no atime: empty package
            vote.empty_package = vote.empty_package + 1
        elif now - entry.atime > 30 * 24*3600:  # 30 days since last use: old
            vote.old_unused = vote.old_unused + 1
        elif now - entry.ctime < 30 * 24* 3600 \
          and entry.atime - entry.ctime < 24*3600:  # upgraded too recently
            vote.too_recent = vote.too_recent + 1
        else:                        # otherwise, vote for this package
            vote.yes = vote.yes + 1

deplist = {}
provlist = {}

class Stat:
  def __init__(self):
    self.vote = {}
    self.vendor = {}
    self.release = {}
    self.arch = {}
    self.count = 0

  def output(self,filename):
    out = open(filename, 'w')
    out.write("Submissions: %8d\n" % self.count)
    releaselist = list(self.release.keys())
    releaselist.sort()
    for release in releaselist:
        out.write("Release: %-30s %5d\n"
                      % (release, self.release[release]))
    archlist = list(self.arch.keys())
    archlist.sort()
    for arch in archlist:
        out.write("Architecture: %-30s %5d\n"
                      % (arch, self.arch[arch]))
    vendorlist = list(self.vendor.keys())
    vendorlist.sort()
    for vendor in vendorlist:
        out.write("Vendor: %-30s %5d\n"
                      % (vendor, self.vendor[vendor]))
    pkglist = list(self.vote.keys())
    pkglist.sort()
    for package in pkglist:
            fv = self.vote[package]
            out.write("Package: %-30s %5d %5d %5d %5d\n"
                      % (package, fv.yes, fv.old_unused,
                         fv.too_recent, fv.empty_package))
    out.close()

stat = Stat()
stat_stable = Stat()

def parse_depends(depline):
    l = []
    split = depline.split(',')
    for d in split:
        x = d.split()
        if (x):
                l.append(x[0])
    return l


def read_depends(filename):
    file = lzma.LZMAFile(filename, "r")
    package = None

    while 1:
        try:
          line = str(file.readline(),encoding='latin_1')
        except:
          line = False
        if line:
            if line[0]==' ' or line[0]=='\t': continue  # continuation
            split = line.split(':')

        if not line or split[0]=='Package':
            if package and (len(dep) > 0 or len(prov) > 0):
                deplist[package] = dep
                for d in prov:
                    if not (d in provlist):
                        provlist[d] = []
                    provlist[d].append(package)
            if package:
                package = None
            if line:
                package = split[1].strip()
                dep = []
                prov = []
        elif split[0]=='Depends' or split[0]=='Requires':
            dep = dep + parse_depends(split[1])
        elif split[0]=='Provides':
            prov = parse_depends(split[1])

        if not line: break

class Entry:
    atime = 0;
    ctime = 0;
    mru_file = '';

    def __init__(self, atime, ctime, mru_file):
        try:
                self.atime = int(atime)
                self.ctime = int(ctime)
        except:
                self.atime = self.ctime = 0
        self.mru_file = mru_file

def istimestamp(s):
  return s.isdigit() or (s[0]=='-' and s[1:].isdigit())

class Submission:
    # format: {package: [atime, ctime, mru_file]}
    entries = {}

    start_date = 0

    arch = "unknown"
    release= "unknown"
    vendor= "Debian"

    # initialize a new entry with known data
    def __init__(self, version, owner_id, date):
        self.entries = {}
        self.start_date = int(date)
        self.id = owner_id

    # process a line of input from the survey
    def addinfo(self, split):
        if (len(split) < 4 or not istimestamp(split[0])
                           or not istimestamp(split[1])):
            ewrite(self.id + ': Invalid input line: ' + repr(split))
            return
        self.entries[split[2]] = Entry(split[0], split[1], split[3])

    # update the atime of dependency to that of dependant, if newer
    def update_atime(self, dependency, dependant):
        if not (dependency in self.entries): return
        e = self.entries[dependency]
        f = self.entries[dependant]
        if e.atime < f.atime:
            e.atime = f.atime
            e.ctime = f.ctime

    # we found the last line of the survey: finish it
    def done(self, date, st):
        st.count = st.count + 1
        for package in self.entries.keys():
            if package in deplist:
                for d in deplist[package]:
                    self.update_atime(d, package)
                    if d in provlist:
                        for dd in provlist[d]:
                            self.update_atime(dd, package)
        for package in self.entries.keys():
            if not (package in st.vote):
                st.vote[package] = Vote()
            st.vote[package].vote_for(package, self.entries[package])

        if not (self.vendor in st.vendor):
            st.vendor[self.vendor] = 1
        else:
            st.vendor[self.vendor] = st.vendor[self.vendor] + 1

        if not (self.release in st.release):
            st.release[self.release] = 1
        else:
            st.release[self.release] = st.release[self.release] + 1
        ewrite("#%s %s" % (st.release[self.release], self.release))

        if not (self.arch in st.arch):
            st.arch[self.arch] = 1
        else:
            st.arch[self.arch] = st.arch[self.arch] + 1

def headersplit(pairs):
    header = {}
    for d in pairs:
        list = d.split(':')
        try:
                key, value = list
                header[key] = value
        except:
                pass
    return header


def read_submissions(stream):
    e = None
    while 1:
        line = str(stream.readline(),encoding='latin_1')
        if not line: break

        split = line.split()
        if not split: continue

        if split[0]=='POPULARITY-CONTEST-0':
            header = headersplit(split[1:])

            if not ('ID' in header) or not ('TIME' in header):
                ewrite('Invalid header: ' + split[1])
                continue

            e = None
            try:
                e = Submission(0, header['ID'], header['TIME'])
            except:
                ewrite('Invalid date: ' + header['TIME'] + ' for ID ' + header['ID'])
                continue

            if 'VENDOR' in header:
                if header['VENDOR']=='':
                    e.vendor = 'unknown'
                else:
                    e.vendor = header['VENDOR']

            if 'POPCONVER' in header:
                if header['POPCONVER']=='':
                    e.release = 'unknown'
                else:
                    e.release = header['POPCONVER']

            if 'ARCH' in header:
                if header['ARCH']=='x86_64':
                    e.arch = 'amd64'
                elif header['ARCH']=='i386-gnu':
                    e.arch = 'hurd-i386'
                elif header['ARCH']=='':
                    e.arch = 'unknown'
                else:
                    e.arch = header['ARCH']

        elif split[0]=='END-POPULARITY-CONTEST-0' and e != None:
            header = headersplit(split[1:])
            if 'TIME' in header:
                try:
                  date = int(header['TIME'])
                except:
                  ewrite('Invalid date: ' + header['TIME'])
                  continue
                e.done(date,stat)
                if e.release==stable_version:
                   e.done(date,stat_stable)
            e = None

        elif e != None:
            e.addinfo(split)
    # end of while loop


# main program

for d in glob.glob('%s/dists/stable/*/binary-i386/Packages.xz' % mirrorbase):
    read_depends(d)
for d in glob.glob('%s/dists/unstable/*/binary-i386/Packages.xz' % mirrorbase):
    read_depends(d)
read_submissions(sys.stdin.buffer)
stat.output("results3")
stat_stable.output("results3.stable")
