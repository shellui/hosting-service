// @ts-check
// Sidebar for docs.shellui.com/hosting. The central site in shellui/shellui
// (tools/docusaurus) loads this file. Doc ids are file names in this folder.

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  tutorialSidebar: [
    {
      type: 'doc',
      id: 'index',
      label: 'Introduction',
    },
    {
      type: 'doc',
      id: 'configuration',
      label: 'Configuration',
    },
    {
      type: 'doc',
      id: 'security-hardening',
      label: 'Security',
    },
    {
      type: 'doc',
      id: 'claim-trust',
      label: 'JWT claim trust',
    },
    {
      type: 'doc',
      id: 'actions',
      label: 'Shellui webhooks',
    },
    {
      type: 'doc',
      id: 'n8n',
      label: 'n8n',
    },
    {
      type: 'doc',
      id: 'event-log',
      label: 'Event log',
    },
  ],
};

module.exports = sidebars;
