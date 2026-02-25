Blender [ResoniteLink](https://github.com/Yellow-Dog-Man/ResoniteLink) extension using [ResoniteLink.py](https://github.com/JackTheFoxOtter/ResoniteLink.py)

(Releases use [my fork of ResoniteLink.py](https://github.com/Nytra/ResoniteLink.py/tree/blender) until PRs are merged)

---

### Things currently implemented:

- Static mesh transfer with any number of material slots (submeshes), UVs, normals and vertex colors.
- No need to apply modifiers first in Blender.
- Object hierarchy replication with correct transforms.
- Remembers slots and components that were already sent over and will re-use them (so long as you don't restart Blender or Resonite)

---

### Things not yet implemented:

- Mesh tangents
- No sending of custom materials/textures (Defaults to PBS_VertexColorMetallic on everything)
- No re-creation of non-mesh Blender objects like lights and cameras
- Skinned meshes not yet supported
- Grease pencil strokes not yet supported

---

### Installation:

- First ensure your Blender version is equal or newer than 4.2.0.
- In Blender, go to Edit -> Preferences and select `Get Extensions`, then click the small downwards-pointing arrow button in the top right, then click `Install from Disk`,
    when prompted, select the zip file downloaded from the [release page](https://github.com/Nytra/Blender_ResoniteLink/releases/latest).
- For more information, see the `Install from Disk` section on [this page](https://docs.blender.org/manual/en/latest/editors/preferences/extensions.html).

---

To use the add-on you need to enable online-mode in the Blender preferences. Preferences->System->Network

The ResoniteLink panel will appear in the scene properties pane on the right-hand side of the Blender window.

<img width="770" height="679" alt="Screenshot_20260219_120155" src="https://github.com/user-attachments/assets/1acd459a-b03b-4569-a567-9b1ef68511c9" />

Type in the websocket port and then hit connect and you can now use the "Send Scene" button to send the current scene hierarchy and meshes to Resonite.

No generative AI was used to create this.
