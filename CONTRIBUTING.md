# Contributing an Open-Source Plugin to Canvas Medical

How to add a plugin you built to the public Canvas plugins repo.

Plugins live here, inside the `extensions/` folder:
**https://github.com/Medical-Software-Foundation/canvas**

---

## 1. Set up

- Create a free GitHub account: https://github.com/signup
- Fork the repo: go to https://github.com/Medical-Software-Foundation/canvas and click **Fork** (top right). This makes your own copy to work in.

---

## 2. Build your plugin folder

Each plugin gets its own folder inside `extensions/`. Copy the layout of an existing one, like `extensions/billing-dashboard/`. A plugin folder contains:

- `README.md` - what it does and how to use it
- `LICENSE` - the license for your code
- `pyproject.toml` - the plugin config file
- a code folder named after your plugin
- `tests/` - tests for the plugin

Match an existing plugin's structure as closely as you can.

### What to put in the README

The README is how reviewers and users understand your plugin. Include these sections:

- **Title** - the plugin name.
- **What it does** - a short paragraph on what the plugin does when installed.
- **Problem it solves** - the pain point it addresses and why it is useful.
- **Who it's for** - the roles or specialties that benefit.
- **How to install** - the `canvas install <plugin_name>` command, plus any SDK commands or settings that must be enabled on the instance.
- **Configuration options** - any secrets, environment variables, or settings to customize. If there are none, say so.
- **Screenshots** - if the plugin has a visible interface.

---

## 3. Add your files and open a pull request

Pick whichever method you are comfortable with. All three end in a pull request (PR), which is how you submit your work.

### Website (easiest, no installs)

1. In your fork, go to the `extensions/` folder.
2. **Add file > Upload files** to drag in your whole plugin folder, or **Add file > Create new file** to add them one at a time. To make a folder, type the folder name and a slash in the filename box: `my-plugin/README.md`.
3. Click **Compare & pull request**, confirm it targets `Medical-Software-Foundation/canvas` `main`, add a title and description, then **Create pull request**.

Upload docs: https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository

### GitHub Desktop (local copy, no command line)

1. Install GitHub Desktop: https://desktop.github.com
2. **File > Clone repository**, pick your fork.
3. **Branch > New branch**, name it `add-my-plugin`.
4. Add your plugin files on your computer.
5. Write a summary, click **Commit**, then **Push origin**.
6. Click **Preview Pull Request > Create Pull Request**.

### Command line

```bash
git clone https://github.com/YOUR-USERNAME/canvas.git
cd canvas
git checkout -b add-my-plugin
# add your plugin folder under extensions/
git add .
git commit -m "Add my-plugin to extensions"
git push origin add-my-plugin
```

Then open the PR from your fork on GitHub.

---

## 4. After you submit

- The Canvas team reviews your PR. 
- You may get comments or change requests. Reply on the PR and edit the same way you added files; the PR updates automatically.
- Once approved, it gets merged. Your plugin is now part of Canvas open source.

---

## Help

- GitHub forking guide: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo

---

## Want an AI agent to do it for you?

If you use an agent with GitHub and terminal access (like Claude Code), paste the prompt
below and it will do the work for you. Fill in the two bracketed parts first.

```
Contribute a new open-source plugin to Canvas Medical's public repo:
https://github.com/Medical-Software-Foundation/canvas (plugins live in the extensions/ folder).

Do the following for me end to end, using the gh CLI and git:
1. Fork Medical-Software-Foundation/canvas to my account (or use my existing fork) and
   clone it locally.
2. Create a new branch named after the plugin.
3. Build the plugin folder under extensions/, matching the structure of an existing plugin
   like extensions/billing-dashboard/ (README.md, LICENSE, pyproject.toml, a code folder
   named after the plugin, and a tests/ folder). Look at that example first, then follow
   the same conventions.
   The README.md must be Markdown and follow the format of existing plugin READMEs, with
   these sections: title, What it does, Problem it solves, Who it's for, How to install
   (the `canvas install <plugin_name>` command plus any SDK commands or settings that must
   be enabled), and Configuration options (or a note that there are none).
4. Commit the changes and push the branch to my fork.
5. Open a pull request against Medical-Software-Foundation/canvas on the main branch, with
   a clear title and description of what the plugin does.

Show me the plan and the files before pushing or opening the PR, and wait for my approval.

Plugin name: [PLUGIN NAME]
What it does: [DESCRIBE YOUR PLUGIN HERE]
```
