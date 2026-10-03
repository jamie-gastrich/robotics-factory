# Do I need to rebuild and re-source after every change?

Date: 2026-10-03. Workspace-wide (applies to `first_robot` and `rescue_turtle`).

## 1. What we built

This lesson is not about new robot code. It is about the **build and run
loop** around our code: when you edit a file, what do you have to do before
your change shows up? The short answer is *it depends on two things* — what
kind of file you changed, and whether the install tree holds copies or
pointers.

## 2. Why we build it this way

Python runs straight from source. C++ does not. C++ has to be turned into a
binary by a compiler first. That single fact is the whole reason the rules
differ between our two package types.

An **alternative we did not pick**: skip `colcon` and run every node by hand
with a long `PYTHONPATH=...` prefix on every command. It "works" for one
Python file. It breaks the moment you add a C++ package, and it makes every
terminal command longer. `colcon build` plus one `source` line is the price
of admission for the whole ROS 2 ecosystem.

## 3. How the pieces fit together

Think of three rooms in a house.

- **`build/`** is the workshop. Tools work here. You never read from it.
- **`install/`** is the showroom. This is the finished, ready-to-use version
  of the package. This is what actually runs.
- **`log/`** is the notebook. colcon writes down what it did and what broke.

The rule you must never break: **you do not edit anything in `install/`.**
You edit in `src/`, you build, and `install/` gets updated for you.

### The big question: copies or pointers?

After `colcon build`, the `install/` room is filled in one of two ways.

**Copies.** `install/.../rescue_manager.py` is a real, separate file with its
own contents. Editing the one in `src/` does nothing to it. You must build
again.

**Pointers (symlinks).** The file in `install/` is a tiny shortcut that points
back at the file in `src/`. Edit the source, and the install tree is already
seeing the new code. No rebuild.

A **symlink** is a shortcut file. Open it and you land in the real file. Open
the real file and you get the real contents.

`--symlink-install` is the flag that asks colcon to use pointers for the files
it can. It is a big speed win for Python, because you skip the copy step
entirely.

### Now the important part: what OUR tree actually looks like

I checked. **Our `install/` tree right now contains zero symlinks.**

```
install/rescue_turtle/lib/python3.14/site-packages/rescue_turtle/
-rw-r--r--  rescue_manager.py     <- a real file, not a shortcut
```

The files are plain copies with a fresh timestamp. So our current install tree
was **not** built with `--symlink-install`, even though our `AGENTS.md` says we
use it.

What this means for you *right now*: there is an uncommitted edit to
`src/rescue_turtle/rescue_turtle/rescue_manager.py` (13 lines added, 3
changed). If you `ros2 run rescue_turtle rescue_manager` at this moment, **you
will run the old code and think your change is broken.** It isn't. Rebuild
first.

### The rule table

| What you changed | Rebuild? |
|---|---|
| A `.py` file in `src/`, built **with** `--symlink-install` | **No** |
| A `.py` file in `src/`, built **without** it (our tree right now) | **Yes** |
| A `.cpp` or `.hpp` file, any time | **Yes, always** |
| `setup.py`, `package.xml`, or `CMakeLists.txt` | **Yes** |
| A brand-new `.py` file | **Yes** (it is not installed yet) |
| A comment or a docstring | No |

Two gotchas hide inside "no rebuild needed for Python":

1. **A new file needs a build.** With symlinks, colcon still had to be told
   the file exists. Add `helper.py` and nothing links it until you rebuild.
2. **A new executable needs a build.** The list of runnable commands lives in
   `setup.py`, not in your code. See section 5.

### Why C++ always needs a build

`colcon build` runs `cmake` and then `g++`. That turns `rescue_manager.cpp`
into a file like `librescue_manager.so` — a shared library, a `.so` file. That
is a real, separate file with your logic already frozen inside it.

Change one line of the `.cpp` and the `.so` on disk still holds the old logic.
There is no shortcut, because your source is not what runs. Only the compiled
`.so` runs. So: C++ means rebuild every time. Always. No exceptions.

### Why `source` is a separate thing from `build`

This is the part people mix up. They are two different jobs.

- **`build`** refreshes the *files* in `install/`.
- **`source`** teaches your *shell* where `install/` is.

Building does not tell your shell anything. Your shell is a program that
started this morning with a fixed list of settings, called **environment
variables** — short names pointing at folders. Some of those names decide
where Linux looks for programs.

`source install/setup.bash` reads a script that rewrites those names so they
point into our workspace. The big ones:

- `PATH` — the list of folders Linux searches when you type a command name.
- `AMENT_PREFIX_PATH` — the list of installed ROS packages. ROS uses this to
  answer "does package `turtlesim` exist, and where?"
- `PYTHONPATH` — the list of folders Python searches for `import`.
- `LD_LIBRARY_PATH` — where Linux looks for compiled `.so` libraries at
  runtime. This is the C++ one.

**Analogy:** your built executables live in a warehouse across town. `build`
is the factory that stocks the warehouse. `source` is writing the warehouse's
address into your phone. Building all night does nothing if your phone has no
address for it.

### "Source is required in every new shell"

That line in our `AGENTS.md` is about environment variables, and it is exactly
true.

Environment variables belong to **one process**. When you set one, it lives in
that process's memory and nowhere else. A new terminal window is a brand-new
process with a clean, empty set. It has never heard of our warehouse.

So `ros2 run rescue_turtle rescue_manager` searches `PATH`, finds nothing,
and fails — not because the code is bad, but because this shell has an empty
notebook. One `source` line fixes it. It costs you half a second. Just always
do it.

### One shell is one environment

Same idea, one step further. If you `source` in terminal 1, **terminal 2 does
not get it.** Environments do not spread between shells. Source in every
terminal you open.

### Backgrounded nodes die with the shell

You might try to keep a node running by adding `&`:

```
ros2 launch rescue_turtle rescue_turtle.launch.py &
```

The `&` puts it in the background, but it is still the **child** of that
shell. When the shell exits, the child gets a hangup signal (`SIGHUP`) and
dies with it.

**Analogy:** that `&` is a child holding your hand. The child is still holding
your hand, so it keeps walking. When you let go — when you close the terminal
— the child stops and stands still.

To make it truly independent, **detach** it with `setsid`:

```
setsid ros2 launch rescue_turtle rescue_turtle.launch.py &
```

` setsid` starts the program in a brand-new session, with no parent shell to
lose. It survives the terminal closing.

### Why `build/`, `install/`, and `log/` are gitignored

They are **generated**, not written by hand. Anything `colcon` can produce, we
can throw away and produce again.

Our root `.gitignore` lists exactly that:

```
ros2_ws/build/
ros2_ws/install/
ros2_ws/log/
__pycache__/
```

Two reasons to keep them out of git:

1. **Size and churn.** They are big, and they change on every build. Every
   commit that touched them would be noise.
2. **They are machine-specific.** Your `install/` has *your* absolute paths
   baked into it. It means nothing on my machine. Git history full of that is
   worthless weight.

Because they are disposable, `AGENTS.md` says you may delete them freely to
force a clean rebuild. They are not precious. They are not source.

## 4. Key words

- **`colcon`** — the ROS 2 build tool. Reads every package under `src/` and
  builds each one.
- **`colcon build`** — the command that does the building. Creates `build/`,
  `install/`, and `log/`.
- **package** — one folder of code with a `package.xml` in it. Ours are
  `first_robot` and `rescue_turtle`.
- **`ament_python`** — a Python package type. Built with `setuptools`. No
  compiler. Runs from source.
- **`ament_cmake`** — the C++ package type. Built with `cmake` plus a C++
  compiler. Produces real binaries. *(We have no package of this type yet.)*
- **`--symlink-install`** — build flag. Put shortcuts in `install/` instead of
  copies, so Python edits need no rebuild.
- **symlink** — a shortcut file that points at another file.
- **install tree** — the `install/` folder. The finished, runnable version.
- **`source`** — a shell command that points your shell's environment
  variables at the install tree.
- **environment variable** — a named setting belonging to one process, like
  `PATH`.
- **`PATH`** — the list of folders searched when you type a command name.
- **`PYTHONPATH`** — the list of folders searched by `import`.
- **`LD_LIBRARY_PATH`** — the list of folders searched for compiled `.so`
  libraries.
- **`AMENT_PREFIX_PATH`** — the list of installed ROS packages.
- **console_scripts** — the `setup.py` list of runnable command names. Fixed at
  build time.
- **`setup.bash`** — the script `source` reads.
- **gitignored** — on a list of files git should not track.
- **child process** — a program started by another program. Dies with it
  unless detached.
- **`setsid`** — the command that detaches a program into its own session so it
  outlives the shell.

## 5. A few lines of code, explained line by line

This is not robot logic. It is `setup.py`, and it is the reason a *new*
executable needs a rebuild even when Python edits do not.

From `ros2_ws/src/rescue_turtle/setup.py`:

```python
entry_points={
    'console_scripts': [
        'spawner = rescue_turtle.spawner:main',
        'rescue_manager = rescue_turtle.rescue_manager:main',
    ],
},
```

Line by line:

- `entry_points=` — "here are the commands this package can be run as."
- `'console_scripts'` — a setuptools category meaning "make a plain command
  line program out of this."
- `'spawner = rescue_turtle.spawner:main'` — read this as three parts:
  `spawner` (the name you type), `rescue_turtle.spawner` (the Python file),
  `main` (the function to call). So `ros2 run rescue_turtle spawner` runs the
  `main` function in that file.
- The closing brackets — a plain Python dictionary and list.

**Why this matters for rebuilding:** the list of runnable names is written
into `install/` **at build time**. `colcon` physically creates a little script
named `spawner` in `install/`. If you add a new entry here, or rename one,
`colcon` has not made that new script yet. The name does not exist on disk.

So, to be exact:

- Edit the **body** of `rescue_manager.py` → symlink means no rebuild.
- Add a **new entry** to `console_scripts` → rebuild.

## 6. Check yourself

1. You are using `--symlink-install` and you fix a typo inside
   `rescue_turtle/spawner.py`. Do you rebuild before running? Why?
2. You add a brand-new file `rescue_turtle/path_planner.py`, and you import
   it from `spawner.py`. Do you rebuild? Why?
3. Your build is fine and you close the terminal, then open a new one and type
   `ros2 run rescue_turtle spawner`. It cannot find the command. What single
   command fixes it, and what is it actually doing?

---

**Answers**

1. No. With `--symlink-install`, the file in `install/` is a symlink pointing
   back at your source file, so the install tree is already reading your fixed
   source. Edit and run again.
2. Yes. Symlinks are only created for files that existed at build time.
   colcon has not been told `path_planner.py` exists, so it is not in the
   install tree yet and the `import` will fail.
3. `source install/setup.bash`. It rewrites your shell's environment variables
   — `PATH`, `AMENT_PREFIX_PATH`, `PYTHONPATH`, `LD_LIBRARY_PATH` — so they
   point into `install/`. The new terminal started with an empty environment
   and had no idea where to look.

## 7. Say it in an interview

> `colcon build` and `source` do two different jobs. Build refreshes the files
> in `install/`; source tells my shell where `install/` is, by setting
> environment variables like `PATH` and `AMENT_PREFIX_PATH`. With
> `--symlink-install`, editing a Python file needs no rebuild because the
> install tree holds symlinks back to my source — but C++ always needs one,
> because what runs is a compiled `.so`, not my source. And since environment
> variables belong to a single process, every new shell needs its own
> `source` before `ros2 run` can find anything.

## 8. What's next

Three real things I noticed in this workspace. I am the Professor and I do not
change code, so these are for the human:

1. **The install tree is copies, not symlinks.** It should have been built
   with `--symlink-install`. Rebuilding with the flag will make the Python
   edit loop instant. Until then, rebuild after every Python edit.
2. **Stray `build/`, `install/`, and `log/` folders inside
   `src/rescue_turtle/`.** Someone ran `colcon` from inside the package folder
   instead of from `ros2_ws/`. git shows them as untracked, because the
   `.gitignore` patterns (`ros2_ws/build/`) are anchored to the root and do not
   match a nested path. They are safe to delete.
3. **`first_robot` has never been built.** There is no `first_robot` folder in
   `install/`, so it has never had a successful build in this workspace.
